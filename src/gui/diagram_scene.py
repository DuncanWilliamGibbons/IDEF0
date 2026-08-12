from PyQt6.QtWidgets import QGraphicsScene
from PyQt6.QtCore import QRectF, pyqtSignal
from PyQt6.QtGui import QColor
from src.core.model import Diagram, ArrowType, Point, generate_icom_codes, simplify_path
from src.gui.diagram_items import (ActivityBoxItem, ArrowItem, make_rounded_path,
                                   resolve_label_overlaps)
from src.core.layout import manhattan_route, natural_sort_key
from src.gui.frame_item import DiagramFrameItem
import pickle
import math
import re

# Corner rounding radius shared by the router, the junction snapper and the
# renderer. Every rounded corner eats this many pixels off each of its legs, so
# junction geometry has to reason about it explicitly.
JUNCTION_RADIUS = 10


def _ortho_unit(dx, dy):
    """Snap a vector to the closest orthogonal unit vector ((0,0) if degenerate)."""
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return (0.0, 0.0)
    if abs(dx) >= abs(dy):
        return (1.0 if dx > 0 else -1.0, 0.0)
    return (0.0, 1.0 if dy > 0 else -1.0)


def _reserved_radius(pts, i, radius=JUNCTION_RADIUS):
    """Upper bound on the arc radius make_rounded_path() consumes at vertex i.

    Terminal vertices are never rounded, so they reserve nothing. Over-estimating
    is safe (the child merges a little deeper into straight material); under-
    estimating leaves the child floating inside the arc, which is what produced
    the gaps at bends.
    """
    n = len(pts)
    if i <= 0 or i >= n - 1:
        return 0.0
    d1 = math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y)
    d2 = math.hypot(pts[i + 1].x - pts[i].x, pts[i + 1].y - pts[i].y)
    return min(radius, d1, d2)


def _junction_tree(arrow_id, arrows):
    """Ids of every arrow reachable from arrow_id through branch/join relations."""
    adj = {}
    for a in arrows:
        for other in (a.branch_parent_id, a.join_target_id):
            if other:
                adj.setdefault(a.id, set()).add(other)
                adj.setdefault(other, set()).add(a.id)
    seen, stack = {arrow_id}, [arrow_id]
    while stack:
        for nxt in adj.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _host_candidates(child, rel, arrow_map, arrows):
    """Arrows that could physically carry child's junction, best guess first.

    The declared parent is only a *logical* link: chained branches routinely tap
    the grandparent's trunk (or the root bus) instead, so the ancestor chain is
    walked before falling back to the rest of the junction tree.
    """
    ordered, seen = [], set()
    cur_id = child.branch_parent_id if rel == 'branch' else child.join_target_id
    while cur_id and cur_id not in seen:
        seen.add(cur_id)
        cur = arrow_map.get(cur_id)
        if not cur:
            break
        ordered.append(cur)
        cur_id = cur.branch_parent_id or cur.join_target_id
    for aid in sorted(_junction_tree(child.id, arrows)):
        if aid != child.id and aid not in seen and aid in arrow_map:
            seen.add(aid)
            ordered.append(arrow_map[aid])
    return ordered


def _tap_points(arrow):
    """The branch/join endpoints this arrow hangs off another arrow with."""
    out = []
    if arrow.segments:
        if arrow.branch_parent_id:
            out.append(arrow.segments[0])
        if arrow.join_target_id:
            out.append(arrow.segments[-1])
    return out


def find_host_segment(child, rel, arrow_map, arrows, radius=JUNCTION_RADIUS, tol=2.0):
    """Locate the arrow segment a branch/join tap actually sits on.

    Returns {'host', 'index', 'parallel', 'leg', 'alternatives'} or None when
    nothing in the junction tree carries the tap (in which case no rounding
    runway is emitted, rather than an invented one pointing nowhere).
    """
    pts = child.segments
    if len(pts) < 2:
        return None
    if rel == 'branch':
        tap, nbr = pts[0], pts[1]
        leg = _ortho_unit(nbr.x - tap.x, nbr.y - tap.y)
    else:
        tap, nbr = pts[-1], pts[-2]
        leg = _ortho_unit(tap.x - nbr.x, tap.y - nbr.y)
    if leg == (0.0, 0.0):
        return None

    # The declared chain is always eligible; unrelated peers that merely tap the
    # same point are not - two branches off one trunk must not host each other.
    ancestors, cur_id = set(), (child.branch_parent_id if rel == 'branch' else child.join_target_id)
    while cur_id and cur_id not in ancestors:
        ancestors.add(cur_id)
        cur = arrow_map.get(cur_id)
        if not cur:
            break
        cur_id = cur.branch_parent_id or cur.join_target_id

    hosted, fallback = [], None
    for rank, host in enumerate(_host_candidates(child, rel, arrow_map, arrows)):
        if host.id not in ancestors and any(
                abs(p.x - tap.x) < 2 and abs(p.y - tap.y) < 2 for p in _tap_points(host)):
            continue
        hp = host.segments
        for i in range(len(hp) - 1):
            q1, q2 = hp[i], hp[i + 1]
            L = math.hypot(q2.x - q1.x, q2.y - q1.y)
            if L < 1e-6:
                continue
            ux, uy = (q2.x - q1.x) / L, (q2.y - q1.y) / L
            t = (tap.x - q1.x) * ux + (tap.y - q1.y) * uy
            perp = abs(-(tap.x - q1.x) * uy + (tap.y - q1.y) * ux)
            outside = max(0.0, -t, t - L)
            # A tap on a host *corner* matches both legs; the child can only lie
            # along the one parallel to its own first/last leg.
            parallel = abs(ux * leg[0] + uy * leg[1]) > 0.5
            ref = {'host': host, 'index': i, 'parallel': parallel, 'leg': leg}
            if perp <= tol and outside <= 4 * radius:
                # Nearest relative first, then segments the tap actually lands
                # inside, and only then the leg the child can lie along - a far
                # overshoot must never win a tie against a segment under the tap.
                hosted.append(((rank, 0 if outside <= radius else 1,
                                0 if parallel else 1, outside, i), ref))
            elif fallback is None or perp + outside < fallback[0]:
                fallback = (perp + outside, ref)

    if hosted:
        hosted.sort(key=lambda kv: kv[0])
        chosen = hosted[0][1]
        chosen['alternatives'] = [r for _, r in hosted[1:]]
        return chosen
    if fallback and fallback[0] <= tol + radius:
        fallback[1]['alternatives'] = []
        return fallback[1]
    return None


def _host_frame(ref, radius=JUNCTION_RADIUS):
    """Live geometry of a host segment: origin, direction and the span of it that
    survives corner rounding. Read fresh so later edits to the host are picked up."""
    hp = ref['host'].segments
    i = ref['index']
    if i + 1 >= len(hp):
        return None
    q1, q2 = hp[i], hp[i + 1]
    L = math.hypot(q2.x - q1.x, q2.y - q1.y)
    if L < 1e-6:
        return None
    u = ((q2.x - q1.x) / L, (q2.y - q1.y) / L)
    lo = _reserved_radius(hp, i, radius)
    hi = L - _reserved_radius(hp, i + 1, radius)
    if hi < lo:
        lo = hi = L / 2.0
    return q1, u, L, lo, hi


def snap_junction_endpoints(diagram, arrow_map, radius=JUNCTION_RADIUS):
    """Pull every branch/join endpoint onto material its host actually draws.

    A tap left sitting on a bare corner vertex renders as a floating stub: the
    host's arc has already cut that corner away. Shallowest arrows are snapped
    first so a child always sees its host's final geometry.
    """
    depth = {}

    def junction_depth(aid, guard=None):
        if aid in depth:
            return depth[aid]
        guard = guard or set()
        if aid in guard:
            return 0
        guard.add(aid)
        a = arrow_map.get(aid)
        parent_id = (a.branch_parent_id or a.join_target_id) if a else None
        depth[aid] = (junction_depth(parent_id, guard) + 1) if parent_id in arrow_map else 0
        return depth[aid]

    hosts = {}
    ordered = sorted(diagram.arrows, key=lambda a: junction_depth(a.id))
    for arrow in ordered:
        for rel in ('branch', 'join'):
            if rel == 'branch' and not arrow.branch_parent_id:
                continue
            if rel == 'join' and not arrow.join_target_id:
                continue
            ref = find_host_segment(arrow, rel, arrow_map, diagram.arrows, radius)
            if not ref:
                continue
            _snap_tap_to_host(arrow, rel, ref, radius)
            hosts[(arrow.id, rel)] = ref
    return hosts


def _snap_tap_to_host(arrow, rel, ref, radius=JUNCTION_RADIUS):
    """Move one branch/join endpoint onto drawn host material, keeping the
    child's own legs orthogonal."""
    frame = _host_frame(ref, radius)
    if not frame:
        return
    q1, (ux, uy), _L, lo, hi = frame
    pts = arrow.segments
    tap = pts[0] if rel == 'branch' else pts[-1]
    nbr = pts[1] if rel == 'branch' else pts[-2]
    t = (tap.x - q1.x) * ux + (tap.y - q1.y) * uy

    if ref['parallel']:
        # The child runs *along* the host, so sliding its tap only lengthens or
        # shortens its own leg - always safe, and it is what lifts the tap out
        # of the host's rounded corner.
        t_new = min(max(t, lo), hi)
        if abs(t_new - t) < 0.5:
            return
        t_nbr = (nbr.x - q1.x) * ux + (nbr.y - q1.y) * uy
        # Stay clear of simplify_path()'s minimum segment length, or the leg we
        # just shortened would be dropped and take the endpoint with it.
        if abs(t_nbr - t_new) < 8.0 or (t_nbr - t) * (t_nbr - t_new) <= 0:
            return  # would collapse or flip the child's leg
        tap.x, tap.y = q1.x + ux * t_new, q1.y + uy * t_new
    else:
        # T-tap: drop it exactly onto the host's centre line.
        nx, ny = -uy, ux
        off = (tap.x - q1.x) * nx + (tap.y - q1.y) * ny
        if abs(off) > 1e-6:
            tap.x -= nx * off
            tap.y -= ny * off
        # If it has drifted past the drawn extent, slide the whole leg back in.
        # Both ends of the leg move together, so it stays orthogonal.
        if len(pts) >= 3:
            shift = min(max(t, lo), hi) - t
            if abs(shift) > 0.5:
                tap.x += ux * shift
                tap.y += uy * shift
                nbr.x += ux * shift
                nbr.y += uy * shift

    # junction_point deliberately keeps the *logical* merge location: it feeds
    # back into routing on the next load and drives the junction dots, so it must
    # not absorb this render-time nudge.
    tap.x, tap.y = round(tap.x), round(tap.y)
    nbr.x, nbr.y = round(nbr.x), round(nbr.y)


def junction_runway_point(arrow, rel, ref, radius=JUNCTION_RADIUS):
    """A point `radius` along a host, giving make_rounded_path() a corner to
    sweep the child into. None when no host has straight room for one.

    Branches peel off *upstream* of the tap and joins merge *downstream* of it,
    so the arc follows the flow. Every hosting segment is tried on that side
    before any of them is allowed to supply a backwards runway.
    """
    tap = arrow.segments[0] if rel == 'branch' else arrow.segments[-1]
    refs = [r for r in [ref] + list(ref.get('alternatives') or []) if not r['parallel']]
    for with_flow in (True, False):
        for r in refs:
            frame = _host_frame(r, radius)
            if not frame:
                continue
            q1, (ux, uy), _L, lo, hi = frame
            t = (tap.x - q1.x) * ux + (tap.y - q1.y) * uy
            step = -radius if rel == 'branch' else radius
            if not with_flow:
                step = -step
            t_ext = min(max(t + step, lo), hi)
            if abs(t_ext - t) >= 1.0:
                return Point(round(q1.x + ux * t_ext), round(q1.y + uy * t_ext))
    return None


# Minimum daylight between parallel runs carrying different signals.
MIN_RUN_SEPARATION = 18.0


def _axis_runs(diagram, axis):
    """Straight runs of every arrow on one axis.

    A run counts as movable only when both its endpoints are interior vertices.
    Shifting such a run just restretches the two neighbouring runs, leaving box
    ports and junction taps exactly where the router placed them.
    """
    out = []
    for a in diagram.arrows:
        pts = a.segments
        n = len(pts) - 1
        for i in range(n):
            p, q = pts[i], pts[i + 1]
            if axis == 'V' and abs(p.x - q.x) < 1 and abs(p.y - q.y) > 4:
                lo, hi, coord = min(p.y, q.y), max(p.y, q.y), p.x
            elif axis == 'H' and abs(p.y - q.y) < 1 and abs(p.x - q.x) > 4:
                lo, hi, coord = min(p.x, q.x), max(p.x, q.x), p.y
            else:
                continue
            out.append({'arrow': a, 'i': i, 'coord': coord, 'lo': lo, 'hi': hi,
                        'movable': 1 <= i <= n - 2})
    return out


def _free_band(diagram, axis, run, outer, margin=12.0):
    """The dead space between function boxes that this run can slide inside."""
    low, high = outer
    for b in diagram.boxes:
        if axis == 'V':
            span_lo, span_hi = b.y, b.y + b.height
            near, far = b.x, b.x + b.width
        else:
            span_lo, span_hi = b.x, b.x + b.width
            near, far = b.y, b.y + b.height
        if min(run['hi'], span_hi) - max(run['lo'], span_lo) <= 0:
            continue  # box is not alongside this run
        if far <= run['coord']:
            low = max(low, far)
        elif near >= run['coord']:
            high = min(high, near)
        else:
            return None  # run currently crosses a box; leave it to the router
    low, high = low + margin, high - margin
    return (low, high) if high > low else None


def _neighbour_lengths(arrow, i):
    """Lengths of the two runs a move of segment i would restretch."""
    pts = arrow.segments
    out = []
    for a, b in ((i - 1, i), (i + 1, i + 2)):
        if 0 <= a and b < len(pts):
            out.append(math.hypot(pts[b].x - pts[a].x, pts[b].y - pts[a].y))
    return out


def separate_parallel_runs(diagram, arrow_map, min_sep=MIN_RUN_SEPARATION):
    """Pull apart parallel runs of *different* signals that ended up on top of
    each other even though their corridor had room.

    Branch drops and routed approach lanes pick their coordinate by independent
    rules, so two unrelated arrows can land a couple of pixels apart in an
    otherwise empty gap. Only runs that are actually crowded get moved, and only
    as far as they must - arrows that are already well placed stay put.
    """
    def root(aid, seen=None):
        seen = seen or set()
        cur = arrow_map.get(aid)
        while cur and cur.id not in seen:
            seen.add(cur.id)
            nxt = cur.branch_parent_id or cur.join_target_id
            if not nxt or nxt not in arrow_map:
                return cur.id
            cur = arrow_map[nxt]
        return aid

    xs = [p.x for a in diagram.arrows for p in a.segments]
    ys = [p.y for a in diagram.arrows for p in a.segments]
    if not xs:
        return 0
    outer = {'V': (min(xs), max(xs)), 'H': (min(ys), max(ys))}

    moved = 0
    for axis in ('V', 'H'):
        runs = _axis_runs(diagram, axis)
        for run in runs:
            if not run['movable']:
                continue
            mine = root(run['arrow'].id)
            # everything sharing this corridor that carries a different signal
            rivals = [o for o in runs
                      if o is not run
                      and root(o['arrow'].id) != mine
                      and min(run['hi'], o['hi']) - max(run['lo'], o['lo']) > 10]
            if not any(abs(o['coord'] - run['coord']) < min_sep for o in rivals):
                continue  # not crowded - leave a good route alone

            band = _free_band(diagram, axis, run, outer[axis])
            if not band:
                continue
            lo, hi = band
            blocked = sorted(o['coord'] for o in rivals if lo - min_sep <= o['coord'] <= hi + min_sep)

            best = None
            step = 2.0
            reach = int((hi - lo) / step) + 1
            for k in range(reach + 1):
                for cand in ({run['coord'] - k * step, run['coord'] + k * step}
                             if k else {run['coord']}):
                    if not (lo <= cand <= hi):
                        continue
                    if any(abs(cand - b) < min_sep for b in blocked):
                        continue
                    best = cand
                    break
                if best is not None:
                    break
            if best is None or abs(best - run['coord']) < 0.5:
                continue

            # don't collapse the runs either side into stubs simplify_path would drop
            arrow, i = run['arrow'], run['i']
            pts = arrow.segments
            key = 'x' if axis == 'V' else 'y'
            old = run['coord']
            setattr(pts[i], key, best)
            setattr(pts[i + 1], key, best)
            if min(_neighbour_lengths(arrow, i), default=99) < 10:
                setattr(pts[i], key, old)
                setattr(pts[i + 1], key, old)
                continue
            run['coord'] = best
            moved += 1
    return moved


# A run has to be at least this long before it claims a lane of its own; short
# stubs (junction runways, port approaches) ride in whatever lane they start in.
MIN_LANE_RUN = 15.0


def _straighten_backward_taps(diagram, arrow_map):
    """Pull a branch's tap back to the lane it drops in.

    A branch that leaves its trunk at one X and then runs back along that trunk
    to drop at another leaves a hook pointing against the flow, and the eye
    reads it as the line doubling back on itself. The two Xs are picked by
    different rules - the tap is staggered off the trunk, the drop lane comes
    from the corridor - so they need not agree. The corridor owns the lane, so
    it is the tap that moves: slide it onto the lane and the hook collapses into
    one clean corner.

    Only a jog running *against* the trunk is touched. A branch that opens the
    same way its trunk flows is reading forward, which is what a tap should look
    like.
    """
    for arrow in diagram.arrows:
        pts = arrow.segments
        if len(pts) < 3:
            continue
        parent = arrow_map.get(arrow.branch_parent_id or arrow.join_target_id)
        if not parent or len(parent.segments) < 2:
            continue
        # opens with a horizontal run and then turns vertical
        if not (abs(pts[0].y - pts[1].y) < 1 and abs(pts[0].x - pts[1].x) > 1):
            continue
        if not (abs(pts[1].x - pts[2].x) < 1 and abs(pts[1].y - pts[2].y) > 1):
            continue

        # the trunk's own run at this height, and which way it flows along it
        flow = 0
        lo = hi = 0.0
        for i in range(len(parent.segments) - 1):
            q, r = parent.segments[i], parent.segments[i + 1]
            if abs(q.y - r.y) < 1 and abs(q.y - pts[0].y) < 2 and abs(r.x - q.x) > 1:
                flow = 1 if r.x > q.x else -1
                lo, hi = min(q.x, r.x), max(q.x, r.x)
                break
        if not flow or (pts[1].x - pts[0].x) * flow >= 0:
            continue
        # the lane still has to be a point on the trunk, or the tap leaves it
        if not lo - 1 <= pts[1].x <= hi + 1:
            continue

        old_x = pts[0].x
        pts[0].x = pts[1].x
        del pts[1]
        # the junction dot and the parent's record of the split move with it
        if arrow.junction_point and abs(arrow.junction_point.x - old_x) < 1:
            arrow.junction_point.x = pts[0].x
        for bp in parent.branch_points:
            if abs(bp.x - old_x) < 1 and abs(bp.y - pts[0].y) < 2:
                bp.x = pts[0].x


def _free_bands(diagram, axis, outer, min_width=30.0):
    """The stripes of the diagram that no function box occupies.

    'V' returns X intervals (where vertical runs live), 'H' returns Y intervals.
    These are exactly the corridors an arrow can slide inside without ever
    crossing a box - the white space the drawing has to share out.
    """
    spans = sorted((b.x, b.x + b.width) if axis == 'V' else (b.y, b.y + b.height)
                   for b in diagram.boxes)
    merged = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])

    bands, cursor = [], outer[0]
    for lo, hi in merged:
        if lo - cursor >= min_width:
            bands.append((cursor, lo))
        cursor = max(cursor, hi)
    if outer[1] - cursor >= min_width:
        bands.append((cursor, outer[1]))
    return bands


def _lane_is_pinned(diagram, points, axis, outer):
    """True when a vertex on this channel is fastened to a box edge or to the
    diagram frame, so the whole channel has to stay where it is."""
    for p in points:
        c = p.x if axis == 'V' else p.y
        if abs(c - outer[0]) < 0.6 or abs(c - outer[1]) < 0.6:
            return True
        for b in diagram.boxes:
            if axis == 'V':
                on_edge = abs(c - b.x) < 0.6 or abs(c - (b.x + b.width)) < 0.6
                alongside = b.y - 0.6 <= p.y <= b.y + b.height + 0.6
            else:
                on_edge = abs(c - b.y) < 0.6 or abs(c - (b.y + b.height)) < 0.6
                alongside = b.x - 0.6 <= p.x <= b.x + b.width + 0.6
            if on_edge and alongside:
                return True
    return False


def _lane_stretches(lanes, pinned, lo, hi):
    """Split a band's lanes into the movable stretches between fixed anchors.

    Each stretch is (low_anchor, high_anchor, [lane indices]) - a run of movable
    lanes only ever shares out the space its pinned neighbours leave it.
    """
    out, start, group = [], lo, []
    for idx, coord in enumerate(lanes):
        if idx in pinned:
            if group:
                out.append((start, coord, group))
                group = []
            start = coord
        else:
            group.append(idx)
    if group:
        out.append((start, hi, group))
    return out


def _lane_vertices(diagram, key, lo, hi):
    """Every vertex - drawn and recorded - sitting on one channel.

    Junction records drive label anchoring and the drag handles, so they travel
    with the line rather than being left behind on the old coordinate.
    """
    out = []
    for arrow in diagram.arrows:
        for p in arrow.segments:
            if lo <= getattr(p, key) <= hi:
                out.append((arrow, p, True))
        marks = list(arrow.branch_points) + list(arrow.join_points)
        if arrow.junction_point is not None:
            marks.append(arrow.junction_point)
        for p in marks:
            if lo <= getattr(p, key) <= hi:
                out.append((arrow, p, False))
    return out


def _apply_lane_plan(diagram, key, plan, min_leg=6.0):
    """Move a band's channels in one step; report the ones that cannot go.

    All of them at once, deliberately: lanes routinely slide past each other, so
    re-reading coordinates between moves would let one lane's vertices be swept
    up by the next lane's shift and the two would fuse into a single line.

    Returns the set of lane ids that squeezed a leg below simplify_path()'s floor
    (a leg that short is dropped, taking its vertex with it). On any such find
    the whole plan is rolled back, so the caller can pin the offenders and share
    the band out around them instead.
    """
    saved = [(p, getattr(p, key)) for _i, _t, verts in plan for _a, p, _seg in verts]
    owner = {}
    for lane_id, target, verts in plan:
        for _a, p, _seg in verts:
            owner[id(p)] = lane_id
            setattr(p, key, target)

    blocked = set()
    drawn = {id(a): a for _i, _t, verts in plan for a, _p, seg in verts if seg}
    for arrow in drawn.values():
        pts = arrow.segments
        for i in range(len(pts) - 1):
            d = math.hypot(pts[i + 1].x - pts[i].x, pts[i + 1].y - pts[i].y)
            if 0.01 < d < min_leg:
                blocked |= {owner[id(p)] for p in (pts[i], pts[i + 1]) if id(p) in owner}

    if blocked:
        for p, orig in saved:
            setattr(p, key, orig)
    return blocked


def _lane_profile(diagram, lane_runs, key, perp, lo, hi):
    """What a channel spans, and where each line hanging off it reaches to.

    `arms` holds one (position along the channel, coordinate the line reaches)
    pair per leg that starts or ends on the channel - the legs peeling off it and
    the merges arriving on it alike. Which side of the corridor a channel belongs
    on is decided entirely by these: one whose legs head back out to the left has
    to sit left of one whose legs head right, or the two must cross. Lines that
    merely pass straight through the band are ignored; they cross the channel
    whichever order it is put in.
    """
    arms = []
    for arrow in diagram.arrows:
        pts = arrow.segments
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            if abs(getattr(p, key) - getattr(q, key)) < 1:
                continue        # runs along the channel, not across it
            if abs(getattr(p, perp) - getattr(q, perp)) > 1:
                continue        # not an orthogonal leg
            for near, far in ((p, q), (q, p)):
                if lo <= getattr(near, key) <= hi:
                    arms.append((getattr(near, perp), getattr(far, key)))
    return {'lo': min(r['lo'] for r in lane_runs),
            'hi': max(r['hi'] for r in lane_runs),
            'arms': arms}


def _lane_crossings(inner, outer, inner_at, outer_at):
    """How often two channels would cut each other in this arrangement."""
    n = 0
    for pos, reach in outer['arms']:
        if reach < inner_at and inner['lo'] < pos < inner['hi']:
            n += 1
    for pos, reach in inner['arms']:
        if reach > outer_at and outer['lo'] < pos < outer['hi']:
            n += 1
    return n


def _order_lanes(group, slots, profiles):
    """Which channel takes which slot, by repeatedly swapping adjacent pairs
    that would cut each other less the other way round."""
    order = list(group)
    for _ in range(len(order)):
        settled = True
        for i in range(len(order) - 1):
            a, b = order[i], order[i + 1]
            if _lane_crossings(profiles[b], profiles[a], slots[i], slots[i + 1]) < \
                    _lane_crossings(profiles[a], profiles[b], slots[i], slots[i + 1]):
                order[i], order[i + 1] = b, a
                settled = False
        if settled:
            break
    return order


def equalise_corridor_lanes(diagram, outer_x, outer_y, min_run=MIN_LANE_RUN):
    """Share every empty corridor out equally between the runs crossing it.

    The router picks each coordinate from a purely local rule - a tier index, a
    fraction of one box-to-box gap, a fixed offset off a box edge - so the lines
    that end up in the same white band know nothing about each other and
    routinely bunch against one side of it while the rest sits empty, and land in
    an order that makes them cut across each other on the way out.

    This pass works on the finished geometry instead: for every band of white
    space it collects the channels actually running through it, puts them in the
    order that crosses least, and re-spaces them evenly. Anything pinned to a box
    edge or the diagram frame stays put. Two signals deliberately sharing one
    channel keep sharing it - lanes are keyed by coordinate, not by arrow, so a
    whole bus moves as a unit.
    """
    if not diagram.boxes:
        return 0

    moved = 0
    for axis, outer in (('V', outer_x), ('H', outer_y)):
        key, perp = ('x', 'y') if axis == 'V' else ('y', 'x')
        bands = _free_bands(diagram, axis, outer)
        if not bands:
            continue
        runs = _axis_runs(diagram, axis)

        for lo, hi in bands:
            inside = [r for r in runs
                      if lo + 1 <= r['coord'] <= hi - 1 and r['hi'] - r['lo'] >= min_run]
            if not inside:
                continue

            # Runs a hair apart are one channel, not two lanes to prise open.
            groups = []
            for r in sorted(inside, key=lambda r: r['coord']):
                if groups and r['coord'] - groups[-1][-1]['coord'] <= 1.0:
                    groups[-1].append(r)
                else:
                    groups.append([r])

            spans = [(min(r['coord'] for r in g) - 0.6,
                      max(r['coord'] for r in g) + 0.6) for g in groups]
            lanes = [sum(r['coord'] for r in g) / len(g) for g in groups]
            profiles = [_lane_profile(diagram, g, key, perp, *spans[i])
                        for i, g in enumerate(groups)]
            pinned = {i for i, (a, b) in enumerate(spans)
                      if _lane_is_pinned(diagram,
                                         [p for _a, p, _s in _lane_vertices(diagram, key, a, b)],
                                         axis, outer)}

            # A channel that cannot shift without collapsing a neighbouring leg
            # becomes an anchor for the rest, so one stuck line no longer costs
            # the whole band its spacing.
            for _attempt in range(len(lanes) + 1):
                plan = []
                for low, high, group in _lane_stretches(lanes, pinned, lo, hi):
                    slots = [low + (high - low) * (k + 1) / (len(group) + 1)
                             for k in range(len(group))]
                    for idx, target in zip(_order_lanes(group, slots, profiles), slots):
                        if abs(target - lanes[idx]) < 0.5:
                            continue
                        plan.append((idx, target,
                                     _lane_vertices(diagram, key, *spans[idx])))
                if not plan:
                    break
                blocked = _apply_lane_plan(diagram, key, plan)
                if not blocked:
                    moved += len(plan)
                    break
                pinned |= blocked
    return moved


def get_parent_source_id(arr, arrow_map):
    curr = arr
    while curr:
        if curr.source_box_id:
            return curr.source_box_id
        if curr.branch_parent_id:
            curr = arrow_map.get(curr.branch_parent_id)
        elif curr.join_target_id:
            curr = arrow_map.get(curr.join_target_id)
        else:
            break
    return None

def get_parent_target_id(arr, arrow_map):
    curr = arr
    while curr:
        if curr.target_box_id:
            return curr.target_box_id
        if curr.branch_parent_id:
            curr = arrow_map.get(curr.branch_parent_id)
        elif curr.join_target_id:
            curr = arrow_map.get(curr.join_target_id)
        else:
            break
    return None

def get_root_trunk_id(arr, arrow_map):
    curr = arr
    while curr:
        if curr.join_target_id:
            curr = arrow_map.get(curr.join_target_id)
        elif curr.branch_parent_id:
            curr = arrow_map.get(curr.branch_parent_id)
        else:
            break
    return curr.id if curr else (arr.id if arr else None)

class DiagramScene(QGraphicsScene):
    node_double_clicked = pyqtSignal(str) # Emits box ID
    diagram_properties_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # self.setSceneRect(0, 0, 2000, 2000) # Don't enforce huge fixed rect, let it grow or set in load
        self.diagram_data = None
        self.frame_enabled = False # Toggle state
        self.frame_item = None
        self.history_stack = []
        self.initial_state = None
        
    def on_item_double_clicked(self, item):
        # Called by ActivityBoxItem
        if hasattr(item, 'node_text'):
            # Assuming we can get ID from somewhere. 
            # ActivityBoxItem stores 'node_number' in text, but let's check if it stores ID.
            # In 'load_diagram', we passed ID as last arg to constructor? No.
            # ActivityBoxItem(..., node_number=box.id) ?
            # Line 25: ActivityBoxItem(box.x, box.y, box.width, box.height, box.name, box.id)
            # So node_text holds box.id actually? Or node number?
            # Model has box.id and box.node_number?
            # ActivityBox in create_sample_diagram: id="A1", name="Plan..."
            # Diagram(node_number="A0")
            # Usually ID is "A1", "A2", etc.
            # So yes, item's node number is the ID we want to decompose.
            box_id = item.node_text.toPlainText()
            self.node_double_clicked.emit(box_id)
        
    def load_diagram(self, diagram: Diagram, project_model=None):
        self.clear()
        self.frame_item = None # Reset reference as clear() deletes the C++ items
        
        self.diagram_data = diagram
        self.project_model = project_model # Store for frame updates
        
        # Initialize variables at method scope to prevent UnboundLocalErrors and scope issues in nested functions
        target_pos = None
        target_arrow = None
        target_box = None
        end_x, end_y, end_dir = 0, 0, "right"
        feedback_chains = set()
        
        # Capture initial state for Reset button if not set
        if self.initial_state is None and diagram.boxes:
             # No, empty is fine. Use deep copy.
             self.initial_state = pickle.dumps(diagram)
        
        # Create arrow map for fast lookup
        arrow_map = {a.id: a for a in diagram.arrows}
        box_map = {b.id: b for b in diagram.boxes}

        def get_gap_keys(arrow, is_branch=True):
            if is_branch:
                t_id = arrow.target_box_id
            else:
                if arrow.join_target_id:
                    target = arrow_map.get(arrow.join_target_id)
                    t_id = get_parent_target_id(target, arrow_map) if target else None
                else:
                    t_id = None
            
            # Refinement: Only apply neighbor gap logic to Input/Output arrows.
            # Control/Mechanism branches should remain relative to their parent's source box
            # to preserve connectivity to their vertical parent stems.
            if arrow.type in [ArrowType.INPUT, ArrowType.OUTPUT]:
                t_box = box_map.get(t_id) if t_id else None
                left_box = None
                if t_box:
                    left_boxes = [b for b in diagram.boxes if b.x + b.width <= t_box.x]
                    if left_boxes:
                        left_box = max(left_boxes, key=lambda b: b.x + b.width)
                s_id = left_box.id if left_box else None
            else:
                # Fallback to parent's source box for Control/Mechanism
                if is_branch:
                    parent = arrow_map.get(arrow.branch_parent_id) if arrow.branch_parent_id else None
                    s_id = get_parent_source_id(parent, arrow_map) if parent else None
                else:
                    s_id = arrow.source_box_id
            
            return s_id, t_id
        
        # 0. Synchronize boundaries with parent box (ICOM Sync)
        if project_model:
            project_model.synchronize_boundaries(diagram.node_number)
            # Re-create map as it might have new arrows
            arrow_map = {a.id: a for a in diagram.arrows}
        
        # Capture initial state for Reset button if not set
        if self.initial_state is None and diagram.boxes: # Use boxes check to avoid saving empty shell as state?
             # No, empty is fine. Use deep copy.
             self.initial_state = pickle.dumps(diagram)
        
        # Determine decomposed boxes
        decomposed_ids = set()
        if project_model:
            decomposed_ids = {d.node_number for d in project_model.diagrams}

        # Draw Boxes
        box_map = {} # Map ID to box data for easy arrow lookup
        for box in diagram.boxes:
            has_decomp = box.id in decomposed_ids
            item = ActivityBoxItem(box.x, box.y, box.width, box.height, box.name, box.id, has_decomposition=has_decomp, box_data=box)
            
            # Apply properties from model
            item.set_box_color(QColor(box.color))
            item.set_font_family(box.font_family)
            item.set_font_size(box.font_size)
            item.set_font_bold(box.font_bold)
            item.set_font_italic(box.font_italic)
            
            self.addItem(item)
            box_map[box.id] = box
        # 1. Consolidate boundary signals into buses and generate ICOM codes (ISO 31320-1)
        # This is now handled in the core model to ensure persistence and consistency.
        generate_icom_codes(diagram)

        # Pass 0.5: Automatically link child boundary arrows to parent trunks (e.g. D.2.1.1 -> D.2.1)
        # Only link if the arrow is connected to a box, keeping unassigned stubs neatly placed at the borders.
        for arrow in diagram.arrows:
            if not arrow.branch_parent_id and not arrow.join_target_id and arrow.source_box_id is None and arrow.target_box_id is not None:
                clean_id = (arrow.icom_code or arrow.id or "").strip().lower()
                best_parent = None
                best_len = 0
                for parent_candidate in diagram.arrows:
                    if parent_candidate.id == arrow.id:
                        continue
                    p_code = (parent_candidate.icom_code or parent_candidate.id or "").strip().lower()
                    if not p_code:
                        continue
                    for delim in ['.', '-', '/']:
                        if clean_id.startswith(p_code + delim) and len(p_code) > best_len:
                            best_parent = parent_candidate
                            best_len = len(p_code)
                if best_parent and best_parent.type == arrow.type:
                    arrow.branch_parent_id = best_parent.id

        # 2. Reset arrow geometry to force a clean dynamic re-route for all arrows
        for a in diagram.arrows:
            a.segments = []
            a.junction_point = None
            a.branch_points = []
            a.join_points = []

        # NEW: Robust Feedback Identification (Semantic & Geometric)
        feedback_chains = set()
        for arrow in diagram.arrows:
            is_f = False
            
            # A. Identification by ICOM Code / Label (User hint)
            lbl = (arrow.label or "").lower()
            icom = (arrow.icom_code or "").lower()
            if any(marker in lbl or marker in icom for marker in ['feedback', 'loop', 'f.']):
                is_f = True
            
            # B. Geometric Loopback (Source X > Target X)
            if not is_f:
                s_id = arrow.source_box_id
                curr_s = arrow
                for _ in range(10):
                    if s_id: break
                    if not curr_s.branch_parent_id: break
                    curr_s = arrow_map.get(curr_s.branch_parent_id)
                    if not curr_s: break
                    s_id = curr_s.source_box_id

                t_id = arrow.target_box_id
                curr_t = arrow
                for _ in range(10):
                    if t_id: break
                    if not curr_t.join_target_id: break
                    curr_t = arrow_map.get(curr_t.join_target_id)
                    if not curr_t: break
                    t_id = curr_t.target_box_id

                if s_id and t_id and s_id in box_map and t_id in box_map:
                    if box_map[t_id].x < box_map[s_id].x:
                        is_f = True

            if is_f:
                feedback_chains.add(arrow.id)

        # Arrows that a feedback signal is carried on before it splits away.
        # A feedback loop runs down and under the diagram, so the output it peels
        # off has to be the LAST one on its box's right edge, reading top to
        # bottom - otherwise the loop has to climb back across every output
        # below it before it can start heading back.
        feedback_carriers = set()
        for aid in feedback_chains:
            curr = arrow_map.get(aid)
            seen = set()
            while curr and curr.id not in seen:
                seen.add(curr.id)
                nxt_id = curr.branch_parent_id or curr.join_target_id
                curr = arrow_map.get(nxt_id) if nxt_id else None
                if curr and curr.id not in feedback_chains:
                    feedback_carriers.add(curr.id)

        # Channel-Based Feedback Salt Generation
        # Loops that leave the same box the same way share one physical channel:
        # the drop lane beside that box, then the run under (or over) the whole
        # diagram. The salt is their lane index within it, so they only have to
        # be told apart from the loops they can actually collide with.
        #
        # Within a channel they nest by reach, shortest on the inside. A loop
        # that turns back early sits in the innermost lane and stops there, so a
        # longer loop passing outside it never has a descent to cross - which is
        # exactly what a short loop staggered OUTSIDE a long one has to do.
        feedback_salts = {}
        if feedback_chains:
            def resolved_target(a):
                """(box, type) this feedback arrow reaches, following its joins."""
                curr, t_id, t_type = a, a.target_box_id, a.type
                for _ in range(10):
                    if t_id or not curr.join_target_id:
                        break
                    nxt = arrow_map.get(curr.join_target_id)
                    if not nxt:
                        break
                    t_id, t_type, curr = nxt.target_box_id, nxt.type, nxt
                return box_map.get(t_id or ''), t_type

            def loop_reach_x(aid):
                """How far left the loop runs before it can turn back in.

                An input arrives on the left face, so its loop has to clear the
                whole box; a control or mechanism turns in at a face, part way
                across. Bigger x = shorter loop = further inside.
                """
                tb, t_type = resolved_target(arrow_map[aid])
                if tb is None:
                    return float('-inf')  # runs to the frame: outermost of all
                if t_type == ArrowType.INPUT:
                    return tb.x - 20
                return tb.x + tb.width / 2

            feedback_channels = {}  # (source_box_id, 'over'|'under') -> [arrow_ids]
            for aid in feedback_chains:
                a = arrow_map.get(aid)
                if not a:
                    continue
                # Only Control feedback goes up and over; the rest run under.
                _tb, t_type = resolved_target(a)
                side = 'over' if t_type == ArrowType.CONTROL else 'under'
                feedback_channels.setdefault((a.source_box_id or '', side),
                                             []).append(aid)

            for aids in feedback_channels.values():
                ordered = sorted(aids, key=lambda aid: (-loop_reach_x(aid), aid))
                for i, aid in enumerate(ordered):
                    feedback_salts[aid] = i

        # Group and Sort arrows per box side for Sequential Ordering (ISO 31320-1)
        exit_groups = {bid: {s: [] for s in ['left', 'top', 'bottom', 'right']} for bid in box_map.keys()}
        entry_groups = {bid: {s: [] for s in ['left', 'top', 'bottom', 'right']} for bid in box_map.keys()}
        for arrow in diagram.arrows:
            # 1. Source Exit
            if arrow.source_box_id and arrow.source_box_id in box_map:
                if not arrow.branch_parent_id:
                    exit_groups[arrow.source_box_id]['right'].append(arrow)
            
            # 2. Target Entry (Recursive for Feedback)
            t_box_id, a_type = arrow.target_box_id, arrow.type
            is_feedback = arrow.id in feedback_chains
            if is_feedback and not t_box_id and arrow.join_target_id:
                curr_search = arrow
                for _ in range(10):
                    tgt_search = arrow_map.get(curr_search.join_target_id)
                    if not tgt_search: break
                    if tgt_search.target_box_id:
                        t_box_id, a_type = tgt_search.target_box_id, tgt_search.type
                        break
                    curr_search = tgt_search
            
            if t_box_id and t_box_id in box_map:
                if not arrow.join_target_id or is_feedback:
                    if a_type == ArrowType.INPUT: entry_groups[t_box_id]['left'].append(arrow)
                    elif a_type == ArrowType.CONTROL: entry_groups[t_box_id]['top'].append(arrow)
                    elif a_type == ArrowType.MECHANISM: entry_groups[t_box_id]['bottom'].append(arrow)

        # Pre-Sort and Map each arrow to its specific Entry/Exit sequence index
        arrow_exit_index = {}
        arrow_entry_index = {}
        exit_counts = {bid: {s: 0 for s in ['left', 'top', 'bottom', 'right']} for bid in box_map.keys()}
        entry_counts = {bid: {s: 0 for s in ['left', 'top', 'bottom', 'right']} for bid in box_map.keys()}

        def arrow_sort_key(a):
            curr = a
            for _ in range(10):
                if not curr.branch_parent_id: break
                parent = next((arr for arr in diagram.arrows if arr.id == curr.branch_parent_id), None)
                if not parent: break
                curr = parent
            # The standard's positional code first: C1, C2, C3 IS the reading
            # order ISO/IEC/IEEE 31320-1 lays down for a boundary edge, so
            # ordering the stubs by it puts them on the edge in the sequence a
            # reader expects. The modeller's own id and the label only break
            # ties on arrows the standard gives no code to.
            text = curr.auto_icom_code or curr.icom_code or curr.label or curr.id
            parts = re.split(r'(\d+)', text)
            return [int(p) if p.isdigit() else p.lower() for p in parts]

        # Group all boundary arrows for special visualization at edges
        boundary_lists = {
            'left': [a for a in diagram.arrows if a.type == ArrowType.INPUT and a.source_box_id is None and a.branch_parent_id is None],
            'right': [a for a in diagram.arrows if a.type == ArrowType.OUTPUT and a.target_box_id is None and a.join_target_id is None],
            'top': [a for a in diagram.arrows if a.type == ArrowType.CONTROL and a.source_box_id is None and a.branch_parent_id is None],
            'bottom': [a for a in diagram.arrows if a.type == ArrowType.MECHANISM and a.source_box_id is None and a.branch_parent_id is None]
        }
        boundary_indices = {'left': 0, 'right': 0, 'top': 0, 'bottom': 0}
        
        # Sort boundary lists by label to ensure stable stub/trunk ordering
        for s in boundary_lists:
            boundary_lists[s].sort(key=arrow_sort_key)

        # Define diagram boundaries for external arrows
        if diagram.boxes:
            all_x = [b.x for b in diagram.boxes] + [b.x + b.width for b in diagram.boxes]
            all_y = [b.y for b in diagram.boxes] + [b.y + b.height for b in diagram.boxes]
            max_p_right = max(all_x)
            # Standardize padding to 150px-200px for a clean look
            diagram_left = min(all_x) - 150
            diagram_right = max_p_right + 150
            diagram_top = min(all_y) - 200
            diagram_bottom = max(all_y) + 200
            
            # Dynamic Output Trunk Distribution
            out_trunks = boundary_lists['right']
            gutter_width = diagram_right - max_p_right
            output_trunk_x_map = {}
            output_merge_x_map = {}
            for i, a in enumerate(out_trunks):
                # Distribute equally in the space between the last box and the diagram edge
                output_trunk_x_map[a.id] = max_p_right + (gutter_width * (i + 1) / (len(out_trunks) + 1))
        else:
            diagram_left = 50
            diagram_right = 1050
            diagram_top = 50
            diagram_bottom = 750
            max_p_right = 900
            gutter_width = 150
            output_trunk_x_map = {}
            output_merge_x_map = {}

        # Pre-compute estimated Y coordinates for right boundary trunks to resolve exit sorting correctly.
        trunk_estimated_y = {}
        r_list = boundary_lists.get('right', [])
        for a in r_list:
            # Find all arrows in tree
            tree_arrows = [a.id]
            queue = [a.id]
            while queue:
                curr_id = queue.pop(0)
                for arrow in diagram.arrows:
                    if arrow.branch_parent_id == curr_id or arrow.join_target_id == curr_id:
                        if arrow.id not in tree_arrows:
                            tree_arrows.append(arrow.id)
                            queue.append(arrow.id)
            
            # Find all boxes associated with these arrows
            box_refs = []
            for aid in tree_arrows:
                arr = arrow_map.get(aid)
                if arr:
                    if arr.source_box_id and arr.source_box_id in box_map:
                        box_refs.append(box_map[arr.source_box_id])
                    if arr.target_box_id and arr.target_box_id in box_map:
                        box_refs.append(box_map[arr.target_box_id])
            
            if box_refs:
                box_refs.sort(key=lambda b: natural_sort_key(b.id))
                best_box = box_refs[0]
                trunk_estimated_y[a.id] = best_box.y + best_box.height / 2
            else:
                idx = r_list.index(a)
                count = len(r_list)
                trunk_estimated_y[a.id] = diagram_top + (diagram_bottom - diagram_top) * (idx + 1) / (count + 1)

        # Resolve the dynamic target Y coordinate for ordering exits to minimize crossings
        def get_target_y_for_sorting(arr):
            dest_ys = []
            
            def resolve(curr, depth=0):
                if depth > 10:
                    return
                # If it targets a box
                if curr.target_box_id and curr.target_box_id in box_map:
                    t_box = box_map[curr.target_box_id]
                    dest_ys.append(t_box.y + t_box.height / 2)
                
                # If it joins a trunk
                if curr.join_target_id:
                    tgt = arrow_map.get(curr.join_target_id)
                    if tgt:
                        resolve(tgt, depth + 1)
                
                # If it is a boundary trunk
                if curr.type == ArrowType.OUTPUT and curr.target_box_id is None and curr.join_target_id is None:
                    if curr.id in trunk_estimated_y:
                        dest_ys.append(trunk_estimated_y[curr.id])
                    else:
                        r_list = boundary_lists.get('right', [])
                        if curr in r_list:
                            idx = r_list.index(curr)
                            count = len(r_list)
                            y_pos = diagram_top + (diagram_bottom - diagram_top) * (idx + 1) / (count + 1)
                            dest_ys.append(y_pos)
                    
                # If it has children branching from it, include their destinations too
                children = [a for a in diagram.arrows if a.branch_parent_id == curr.id]
                for child in children:
                    resolve(child, depth + 1)

            resolve(arr)
            if dest_ys:
                return sum(dest_ys) / len(dest_ys)
            return 0

        def get_equidistant_position(box, side, index, total):
            if side == 'left' or side == 'right':
                edge_length = box.height
            else:  # top or bottom
                edge_length = box.width

            if total <= 0:
                return edge_length / 2

            index = min(max(0, index), total - 1)
            segment_size = edge_length / (total + 1)
            return segment_size * (index + 1)

        def chain_root(arr):
            curr = arr
            for _ in range(10):
                if not curr.branch_parent_id:
                    break
                parent = arrow_map.get(curr.branch_parent_id)
                if not parent:
                    break
                curr = parent
            return curr

        def head_lane_y(arr):
            """The height a control travels at just before it drops onto a head
            edge, or None when it comes straight down the head corridor.

            A control that reaches the box from INSIDE the diagram - off another
            box's output, or off an input bus crossing from the left - runs in a
            lane below the corridor and has to turn up into the edge. Any drop
            out of the corridor that lands to its left crosses that run, so it
            has to take the ports on the left and the corridor drops queue to its
            right. Between two such arrows the lower lane goes further left, for
            the same reason: its run is the one the other would have to cross.
            """
            root = chain_root(arr)
            s_box = box_map.get(root.source_box_id)
            if s_box:
                idx = arrow_exit_index.get(root.id, 0)
                return s_box.y + get_equidistant_position(
                    s_box, 'right', idx, exit_counts[s_box.id]['right'])

            if root.source_box_id is None and root.type == ArrowType.INPUT:
                # An input bus enters at the height of the topmost box it feeds -
                # the same rule Pass 1.1 uses to place the trunk itself.
                tree = [root] + [a for a in diagram.arrows
                                 if a.branch_parent_id == root.id]
                fed = [c for c in tree if c.target_box_id in box_map]
                if fed:
                    top = min(fed, key=lambda c: box_map[c.target_box_id].y)
                    t_box = box_map[top.target_box_id]
                    idx = arrow_entry_index.get(top.id, 0)
                    return t_box.y + get_equidistant_position(
                        t_box, 'left', idx, entry_counts[t_box.id]['left'])
            return None

        def geometric_sort_key(arr, side, bid):
            curr = arr
            for _ in range(10):
                if not curr.branch_parent_id: break
                parent = next((a for a in diagram.arrows if a.id == curr.branch_parent_id), None)
                if not parent: break
                curr = parent
            label_fallback = arrow_sort_key(arr)
            # Rank assignment to cluster specific arrow types on box edges
            # Rank -1: Forward output-to-control (placed leftmost on top side)
            # Rank 0/1: Most "Inner" (Forward/Controls)
            # Rank 2: Boundary/ICOM
            # Rank 3: Least "Inner" (Feedback)
            is_f = (arr.id in feedback_chains) or (curr.id in feedback_chains)
            is_internal = curr.source_box_id and curr.target_box_id and not is_f
            
            is_output_to_control = False
            source_box_id = None
            if side == 'top':
                source_box_id = get_parent_source_id(arr, arrow_map)
                if source_box_id is not None and not is_f:
                    is_output_to_control = True

            if is_output_to_control:
                rank = -1
            elif is_internal:
                rank = 0 # Forward
            elif is_f:
                rank = 2 # Feedback (Logical)
            else:
                rank = 1 # Boundary
            
            ox, oy = -99999, -99999
            if curr.source_box_id and curr.source_box_id in box_map:
                s_box = box_map[curr.source_box_id]
                ox, oy = s_box.x + s_box.width, s_box.y + s_box.height/2
            elif is_output_to_control and source_box_id in box_map:
                s_box = box_map[source_box_id]
                ox, oy = s_box.x + s_box.width, s_box.y + s_box.height/2
            elif curr.source_box_id is None:
                p = curr
                while p.branch_parent_id and p.branch_parent_id in arrow_map:
                    p = arrow_map[p.branch_parent_id]
                if p.source_box_id is None and p.type == ArrowType.INPUT:
                    ox = diagram_left
            
            def get_tree_x_for_sorting(a, b_id):
                dest_xs = []
                def resolve(c, depth=0):
                    if depth > 10:
                        return
                    if c.target_box_id and c.target_box_id in box_map:
                        t_box = box_map[c.target_box_id]
                        dest_xs.append(t_box.x + t_box.width / 2)
                    if c.source_box_id and c.source_box_id in box_map:
                        s_box = box_map[c.source_box_id]
                        dest_xs.append(s_box.x + s_box.width / 2)
                    if c.branch_parent_id:
                        parent_arrow = arrow_map.get(c.branch_parent_id)
                        if parent_arrow:
                            resolve(parent_arrow, depth + 1)
                    if c.join_target_id:
                        tgt = arrow_map.get(c.join_target_id)
                        if tgt:
                            resolve(tgt, depth + 1)
                    
                    # Children
                    children = [ch for ch in diagram.arrows if ch.branch_parent_id == c.id]
                    for child in children:
                        resolve(child, depth + 1)
                resolve(a)
                if b_id in box_map:
                    bid_x = box_map[b_id].x + box_map[b_id].width / 2
                    other_xs = [x for x in dest_xs if abs(x - bid_x) > 1e-3]
                    if other_xs:
                        return sum(other_xs) / len(other_xs)
                if dest_xs:
                    return sum(dest_xs) / len(dest_xs)
                return -99999

            def get_tree_y_for_sorting(a, b_id):
                dest_ys = []
                def resolve(c, depth=0):
                    if depth > 10:
                        return
                    if c.target_box_id and c.target_box_id in box_map:
                        t_box = box_map[c.target_box_id]
                        dest_ys.append(t_box.y + t_box.height / 2)
                    if c.source_box_id and c.source_box_id in box_map:
                        s_box = box_map[c.source_box_id]
                        dest_ys.append(s_box.y + s_box.height / 2)
                    if c.branch_parent_id:
                        parent_arrow = arrow_map.get(c.branch_parent_id)
                        if parent_arrow:
                            resolve(parent_arrow, depth + 1)
                    if c.join_target_id:
                        tgt = arrow_map.get(c.join_target_id)
                        if tgt:
                            resolve(tgt, depth + 1)
                    
                    # Children
                    children = [ch for ch in diagram.arrows if ch.branch_parent_id == c.id]
                    for child in children:
                        resolve(child, depth + 1)
                resolve(a)
                if b_id in box_map:
                    bid_y = box_map[b_id].y + box_map[b_id].height / 2
                    other_ys = [y for y in dest_ys if abs(y - bid_y) > 1e-3]
                    if other_ys:
                        return sum(other_ys) / len(other_ys)
                if dest_ys:
                    return sum(dest_ys) / len(dest_ys)
                return -99999

            if ox == -99999:
                ox = get_tree_x_for_sorting(arr, bid)
            if oy == -99999:
                oy = get_tree_y_for_sorting(arr, bid)

            # How far this arrow has to travel to reach the box it lands on.
            # The shortest run takes the first port on the edge - leftmost
            # across the top and bottom, topmost down the side - so a short
            # arrow never has to cut across a longer one to reach a slot past
            # it. Segments do not exist yet at this point, so the reach is
            # measured box to box. It sits below the edge ranking, which
            # carries the IDEF0 reading order, and the geometric keys that used
            # to order the edge now break its ties.
            reach = 0.0
            if bid in box_map:
                t_box = box_map[bid]
                if ox != -99999:
                    reach += abs(ox - (t_box.x + t_box.width / 2))
                if oy != -99999:
                    reach += abs(oy - (t_box.y + t_box.height / 2))

            # The side edge orders by the Y the arrow arrives at, for the same
            # reason the head edge orders by X: inputs reach it across the
            # diagram at the height they left their source, so arrival order is
            # already the order that does not cross. Sorting it by run length
            # instead swaps a long arrow coming from high up below a short one
            # coming from just alongside, and the two trade ports.
            if side == 'left': return (rank, oy, -ox, label_fallback)
            elif side == 'top':
                # The head edge orders by where the arrow arrives FROM, and
                # nothing may sort ahead of that.
                #
                # A control that comes down the head corridor arrives at an X,
                # and arrival X is already the crossing-free order for those: one
                # coming in from the far left that is handed a port on the right
                # has to cut across every drop in between. Ordering the whole
                # edge by run length instead cost 21 crossings across the
                # reference model - see the reach comment above.
                #
                # A control that arrives from INSIDE the diagram does not arrive
                # at an X at all: it runs along a lane under the corridor and
                # turns up into the edge, so every corridor drop landing left of
                # it crosses that run. Those take the left of the edge, lowest
                # lane first, and the corridor queues by X to their right. This
                # is what puts D.4.6 Production Plan first on A33 instead of last
                # behind two boundary controls it had to cut under to get there.
                if rank == 2: return (3, 1, 0.0, -ox, oy, label_fallback) # Feedback Outer
                # A forward output-to-control gets no rank of its own; it is
                # ranked by its lane like anything else arriving from inside.
                # Handing it the leftmost port outright pushed a control arriving
                # from further left past its own drop, and the two crossed for no
                # reason other than the override.
                r = 0 if rank in [-1, 0, 1] else rank
                lane = head_lane_y(arr)
                if lane is None:
                    return (r, 1, 0.0, ox, oy, label_fallback)
                return (r, 0, -lane, ox, oy, label_fallback)
            elif side == 'bottom':
                if rank == 2: return (3, reach, ox, -oy, label_fallback) # Feedback Outer
                return (rank, reach, ox, -oy, label_fallback)
            else: # side == 'right'
                curr_t = arr
                for _ in range(10):
                    if not curr_t.join_target_id: break
                    child = next((a for a in diagram.arrows if a.id == curr_t.join_target_id), None)
                    if not child: break
                    curr_t = child
                tx = 0
                if curr_t.target_box_id and curr_t.target_box_id in box_map:
                    t_box = box_map[curr_t.target_box_id]
                    tx = t_box.x
                
                ty = get_target_y_for_sorting(arr)
                
                # SPECIALIZED OUTPUT RANKING (Source Edge only):
                # 1. Absolute Top -> [-1] Feedback-to-Control (Up and Over)
                # 2. Upper Mid   -> [ 1] Boundary Context Outputs
                # 3. Lower Mid   -> [ 2] Internal Forward Flows (Bottom portion exit)
                # 4. Lower       -> [ 3] Outputs a feedback loop peels off
                # 5. Absolute Bot -> [ 4] Feedback-to-Mechanism (Down and Under)
                r = rank
                if rank == 0: r = 2   # Push Forward (Internal) to lower slots
                elif rank == 1: r = 1 # Keep Boundary in upper mid slots (relative to forward)

                if rank == 2: # Logic for Feedback arrows
                    if curr_t.type == ArrowType.CONTROL:
                        return (-1, ty, -tx, label_fallback) # ABSOLUTE TOP
                    elif curr_t.type in [ArrowType.MECHANISM, ArrowType.INPUT]:
                        return (4, ty, -tx, label_fallback) # ABSOLUTE BOTTOM

                # An output that a feedback loop later branches off drops to the
                # bottom of the edge: the loop turns down and under from there, so
                # leaving from any higher port makes it cross every output below.
                if arr.id in feedback_carriers:
                    r = 3

                return (r, ty, -tx, label_fallback)

        # Populate Exit Indices
        for bid in exit_groups:
            for side in exit_groups[bid]:
                lst = exit_groups[bid][side]
                lst.sort(key=lambda a: geometric_sort_key(a, side, bid))
                exit_counts[bid][side] = len(lst)
                for i, a in enumerate(lst):
                    arrow_exit_index[a.id] = i
        
        # Populate Entry Indices. Sides before boxes, and 'left' before 'top':
        # the head edge is ordered partly by where an input bus crosses the
        # diagram, which is the side edge's answer, and iterating box-first left
        # that answer half computed for whichever boxes came later in the list.
        for side in ['left', 'top', 'bottom', 'right']:
            for bid in entry_groups:
                lst = entry_groups[bid][side]
                lst.sort(key=lambda a: geometric_sort_key(a, side, bid))
                entry_counts[bid][side] = len(lst)
                for i, a in enumerate(lst):
                    arrow_entry_index[a.id] = i

        # Identify arrows that act as trunks (have branches or joins)
        trunk_ids = {a.branch_parent_id for a in diagram.arrows if a.branch_parent_id} | \
                    {a.join_target_id for a in diagram.arrows if a.join_target_id}

        # Track which arrows have been processed for pre-calculation
        calc_indices = {bid: {s: 0 for s in ['left', 'right', 'top', 'bottom']} for bid in box_map.keys()}

        # Pre-calculate exit/entry positions for all non-joining/non-branching arrows
        # to ensure that junctions can "stick" to the correct trunk position.
        arrow_exit_pos = {} # Map arrow.id to its start_y/start_x
        arrow_entry_pos = {} # Map arrow.id to its end_y/end_x

        calc_unassigned = {s: 0 for s in ['left', 'right', 'top', 'bottom']}

        # Pass 1.1: Calculate base exit/entry for all arrows (including stubs)
        for arrow in diagram.arrows:
            s_box = box_map.get(arrow.source_box_id)
            
            # Resolve intended port coordinates surgically for feedback
            t_box_id = arrow.target_box_id
            a_type = arrow.type
            is_feedback = arrow.id in feedback_chains
            if is_feedback and not t_box_id and arrow.join_target_id:
                tgt = arrow_map.get(arrow.join_target_id)
                if tgt: t_box_id, a_type = tgt.target_box_id, tgt.type

            if s_box:
                side = 'right'
                idx = arrow_exit_index.get(arrow.id, 0)
                arrow_exit_pos[arrow.id] = s_box.y + get_equidistant_position(s_box, side, idx, exit_counts[s_box.id][side])
            
            children = [a for a in diagram.arrows if a.branch_parent_id == arrow.id]
            if (children or arrow.branch_parent_id is None) and arrow.source_box_id is None and a_type == ArrowType.INPUT:
                # Align boundary trunk Y with the highest (topmost) target box in the entire tree
                all_tree_nodes = [arrow] + children
                top_child = None
                top_y = 99999
                for ch in all_tree_nodes:
                    if ch.target_box_id and ch.target_box_id in box_map:
                        cb = box_map[ch.target_box_id]
                        if cb.y < top_y:
                            top_y = cb.y
                            top_child = ch
                if top_child and top_child.target_box_id in box_map:
                    t_box = box_map[top_child.target_box_id]
                    idx = arrow_entry_index.get(top_child.id, 0)
                    arrow_entry_pos[arrow.id] = t_box.y + get_equidistant_position(t_box, 'left', idx, entry_counts[t_box.id]['left'])
            elif t_box_id and t_box_id in box_map:
                t_box = box_map[t_box_id]
                idx = arrow_entry_index.get(arrow.id, 0)
                if a_type == ArrowType.INPUT:
                    side = 'left'
                    arrow_entry_pos[arrow.id] = t_box.y + get_equidistant_position(t_box, side, idx, entry_counts[t_box.id][side])
                elif a_type == ArrowType.CONTROL:
                    side = 'top'
                    arrow_entry_pos[arrow.id] = t_box.x + get_equidistant_position(t_box, side, idx, entry_counts[t_box.id][side])
                elif a_type == ArrowType.MECHANISM:
                    side = 'bottom'
                    arrow_entry_pos[arrow.id] = t_box.x + get_equidistant_position(t_box, side, idx, entry_counts[t_box.id][side])
            if arrow.join_target_id and arrow.type == ArrowType.OUTPUT:
                if arrow.id in arrow_exit_pos:
                    arrow_entry_pos[arrow.id] = arrow_exit_pos[arrow.id]
            
            # Boundary stubs/trunks: calculate their projected X/Y so branches/joins can find them
            if not arrow.branch_parent_id and not arrow.join_target_id:
                for s_key in ['top', 'bottom', 'left', 'right']:
                    if arrow in boundary_lists[s_key]:
                        # If it's a trunk-only arrow (no box), use standard spacing
                        if not s_box and not t_box_id:
                            idx, count = boundary_lists[s_key].index(arrow), len(boundary_lists[s_key])
                            if s_key in ['top', 'bottom']:
                                pos = diagram_left + (diagram_right - diagram_left) * (idx + 1) / (count + 1)
                            else:
                                pos = diagram_top + (diagram_bottom - diagram_top) * (idx + 1) / (count + 1)
                            arrow_entry_pos[arrow.id] = pos
                            arrow_exit_pos[arrow.id] = pos
                        
                        # IF IT HAS ONE BOX: The "other end" at the boundary must share the box's Y/X 
                        # so that the horizontal trunk line is flat and branch/join junctions find it.
                        elif s_box and not t_box_id: # Box to Boundary (Output)
                            if arrow.id in arrow_exit_pos:
                                arrow_entry_pos[arrow.id] = arrow_exit_pos[arrow.id]
                        elif t_box_id and not s_box: # Boundary to Box (Input)
                            if arrow.id in arrow_entry_pos:
                                arrow_exit_pos[arrow.id] = arrow_entry_pos[arrow.id]

        # Pass 1.2: Propagate sticky positions to branches and joins
        # This ensures that even nested merges stay connected when the root box spacing changes.
        changed = True
        while changed:
            changed = False
            for arrow in diagram.arrows:
                if arrow.id in arrow_exit_pos: continue
                # Use exit or entry pos depending on which end is connected to the trunk
                parent_id = arrow.branch_parent_id or arrow.join_target_id
                if parent_id:
                    parent_pos = arrow_exit_pos.get(parent_id) or arrow_entry_pos.get(parent_id)
                    if parent_pos is not None:
                        arrow_exit_pos[arrow.id] = parent_pos
                        changed = True

        # Pass 1.3: Calculate tier spacing and map trunks to specific sequential tiers
        # Create "Live Space" definitions for Head (Controls) and Foot (Mechanisms)
        
        all_x_coords = [b.x for b in diagram.boxes] + [b.x + b.width for b in diagram.boxes]
        all_y_coords = [b.y for b in diagram.boxes] + [b.y + b.height for b in diagram.boxes]
        
        min_box_x = min(all_x_coords) if all_x_coords else 200
        max_box_x = max(all_x_coords) if all_x_coords else 800
        min_box_y = min(all_y_coords) if all_y_coords else 200
        max_box_y = max(all_y_coords) if all_y_coords else 600
        
        # Live corridors: the whole white band between the diagram boundary and
        # the nearest function box. Tiers are laid out at span * (i+1)/(n+1)
        # inside the band, so the daylight above the first tier, between tiers,
        # and below the last one is identical. Reserving an arbitrary strip at
        # either end (the old +30/-45 margins) made the tiers bunch against the
        # boundary and left a wide empty gutter hugging the boxes.
        # HEADSPACE (Controls)
        head_live_min = diagram_top
        head_live_max = min_box_y
        head_live_span = max(60, head_live_max - head_live_min)

        # FOOTSPACE (Mechanisms)
        foot_live_min = max_box_y
        foot_live_max = diagram_bottom
        foot_live_span = max(60, foot_live_max - foot_live_min)

        # LEFTSPACE (Inputs)
        left_live_min = diagram_left
        left_live_max = min_box_x
        left_live_span = max(50, left_live_max - left_live_min)

        # RIGHTSPACE (Outputs)
        right_live_min = max_box_x
        right_live_max = diagram_right
        right_live_span = max(50, right_live_max - right_live_min)

        # 1. Identify "Trunks" (the root boundary arrow for a tree of branches)
        # Group all arrows by their root trunk ID so they share the same tier level
        branch_tier_map = {} # arrow_id -> tier_index
        branch_totals = {'top': 0, 'bottom': 0, 'left': 0, 'right': 0}
        
        trunk_groups = {'top': [], 'bottom': [], 'left': [], 'right': []} # List of root_arrow_ids
        
        # Helper to find root
        def get_root_id(aid):
            curr = arrow_map.get(aid)
            while curr and curr.branch_parent_id:
                curr = arrow_map.get(curr.branch_parent_id)
            return curr.id if curr else aid

        # Pass 1.2.1: Pre-calculate Shared Trunk Positions for Vertical and Horizontal Flows
        for arrow in diagram.arrows:
            # Root trunk OR orphaned branch/join (parent missing)
            is_root_potential = (not arrow.branch_parent_id or arrow.branch_parent_id not in arrow_map) and \
                                (not arrow.join_target_id or arrow.join_target_id not in arrow_map)
            if arrow.type in [ArrowType.CONTROL, ArrowType.MECHANISM, ArrowType.INPUT, ArrowType.OUTPUT] and is_root_potential:
                # This is a root trunk. Find all targets (for C/M/I) or sources (for O) in its tree.
                tree_arrows = []
                queue = [arrow.id]
                while queue:
                    curr_id = queue.pop(0)
                    tree_arrows.append(curr_id)
                    # For trunks, include both branches and joins to find the full tree extent
                    children = [a.id for a in diagram.arrows if a.branch_parent_id == curr_id or a.join_target_id == curr_id]
                    queue.extend(children)
                
                target_vals = [] # Positions (X for C/M, Y for I/O)
                for aid in tree_arrows:
                    if aid in arrow_entry_pos: target_vals.append(arrow_entry_pos[aid])
                    if aid in arrow_exit_pos: target_vals.append(arrow_exit_pos[aid])
                
                if target_vals:
                    # Align trunk with the Naturally First associated box
                    box_refs = []
                    for aid in tree_arrows:
                        a = arrow_map[aid]
                        if a.target_box_id and aid in arrow_entry_pos: box_refs.append(aid)
                        elif a.source_box_id and aid in arrow_exit_pos: box_refs.append(aid)
                    
                    if box_refs:
                        best_aid = min(box_refs, key=lambda aid: natural_sort_key(arrow_map[aid].target_box_id or arrow_map[aid].source_box_id))
                        best_val = arrow_entry_pos.get(best_aid) or arrow_exit_pos.get(best_aid)
                        arrow_exit_pos[arrow.id] = best_val
                        # For boundary arrows, ensure the entry/exit stub remains aligned
                        if arrow.source_box_id is None: arrow_entry_pos[arrow.id] = best_val
                        if arrow.target_box_id is None: arrow_exit_pos[arrow.id] = best_val
                    else:
                        best_val = min(target_vals)
                        arrow_exit_pos[arrow.id] = best_val
                        if arrow.source_box_id is None: arrow_entry_pos[arrow.id] = best_val

        # Pass 1.2.2: Re-Propagate sticky positions with updated trunk alignments
        changed = True
        while changed:
            changed = False
            for arrow in diagram.arrows:
                if arrow.source_box_id is not None:
                    continue
                parent_id = arrow.branch_parent_id or arrow.join_target_id
                if parent_id:
                    parent_pos = arrow_exit_pos.get(parent_id) or arrow_entry_pos.get(parent_id)
                    if parent_pos is not None and arrow_exit_pos.get(arrow.id) != parent_pos:
                        arrow_exit_pos[arrow.id] = parent_pos
                        changed = True

        # Pass 1.2.3: Re-calculate output_merge_x_map and output_trunk_x_map using Interval Coloring
        output_merge_x_map = {}
        output_trunk_x_map = {}
        if diagram.boxes:
            out_trunks = boundary_lists['right']
            gutter_width = diagram_right - max_p_right
            
            # Step 1: Calculate vertical spans [y_min, y_max] for each trunk
            spans = {}
            for a in out_trunks:
                y_vals = []
                if a.id in arrow_exit_pos: y_vals.append(arrow_exit_pos[a.id])
                if a.id in arrow_entry_pos: y_vals.append(arrow_entry_pos[a.id])
                for child in diagram.arrows:
                    if get_root_trunk_id(child, arrow_map) == a.id:
                        if child.id in arrow_exit_pos: y_vals.append(arrow_exit_pos[child.id])
                        if child.id in arrow_entry_pos: y_vals.append(arrow_entry_pos[child.id])
                if y_vals:
                    spans[a.id] = (min(y_vals), max(y_vals))
                else:
                    spans[a.id] = (diagram_top, diagram_bottom)
            
            # Step 2: Group trunks into non-overlapping columns (greedy first-fit)
            sorted_trunks = sorted(out_trunks, key=lambda t: spans[t.id][0])
            columns = [] # List of columns, each column is a list of trunk_ids
            
            for t in sorted_trunks:
                t_span = spans[t.id]
                placed = False
                for col in columns:
                    overlap = False
                    for existing_id in col:
                        e_span = spans[existing_id]
                        # Overlap if their closed intervals intersect (including shared endpoints)
                        if max(t_span[0], e_span[0]) <= min(t_span[1], e_span[1]):
                            overlap = True
                            break
                    if not overlap:
                        col.append(t.id)
                        placed = True
                        break
                if not placed:
                    columns.append([t.id])
            
            # Step 3: Assign X coordinates - equidistant across the whole gutter
            # between the rightmost box and the diagram edge, so the buses share
            # the margin instead of crowding together next to the boxes.
            num_cols = len(columns)
            col_0_x = max_p_right + gutter_width / (num_cols + 1)

            for col_idx, col in enumerate(columns):
                col_x = max_p_right + gutter_width * (col_idx + 1) / (num_cols + 1)
                for tid in col:
                    output_trunk_x_map[tid] = col_x
            
            # Step 4: Map all child merge arrows to their parent trunk's X coordinate
            for child in diagram.arrows:
                if child.type == ArrowType.OUTPUT and child.join_target_id is not None:
                    root_parent_id = get_root_trunk_id(child, arrow_map)
                    output_merge_x_map[child.id] = output_trunk_x_map.get(root_parent_id, col_0_x)

        # Pass 1.3: Calculate tier spacing and map trunks to specific sequential tiers
        # ... (rest of Pass 1.3) ...
        branch_tier_map = {} # arrow_id -> tier_index
        branch_sub_tier_map = {} # arrow_id -> branch_index_within_tree
        branch_totals = {'top': 0, 'bottom': 0, 'left': 0, 'right': 0}
        branch_tree_counts = {} # root_id -> total_branches_in_tree
        
        trunk_groups = {'top': [], 'bottom': [], 'left': [], 'right': []} # List of root_arrow_ids
        
        # Group roots
        roots_seen = set()
        sorted_arrows_by_icom = sorted(diagram.arrows, key=arrow_sort_key)
        
        for arrow in sorted_arrows_by_icom:
            if arrow.type == ArrowType.CONTROL: side = 'top'
            elif arrow.type == ArrowType.MECHANISM: side = 'bottom'
            elif arrow.type == ArrowType.INPUT: side = 'left'
            else: side = 'right'
            
            # Only consider actual boundary roots or independent arrows for tiering purposes
            # Signals that branch FROM or join INTO other signals are NOT roots
            is_branch = arrow.branch_parent_id and arrow.branch_parent_id in arrow_map
            is_join = arrow.join_target_id and arrow.join_target_id in arrow_map
            
            if is_branch or is_join:
                continue
            
            root_id = arrow.id
            if root_id not in roots_seen:
                trunk_groups[side].append(root_id)
                roots_seen.add(root_id)
        
        trunk_ids = roots_seen # Unified set of all root trunks

        def trunk_run_length(root_id):
            """How far this trunk's bus has to run along its own tier.

            Every port position is stored on the axis its bus travels - X for
            the control and mechanism buses that run across the head and foot,
            Y for the input buses down the left margin - so the spread of the
            whole tree's ports is the length of the run itself.
            """
            vals = []
            seen, queue = set(), [root_id]
            while queue:
                aid = queue.pop()
                if aid in seen:
                    continue
                seen.add(aid)
                if aid in arrow_entry_pos: vals.append(arrow_entry_pos[aid])
                if aid in arrow_exit_pos: vals.append(arrow_exit_pos[aid])
                queue.extend(a.id for a in diagram.arrows
                             if a.branch_parent_id == aid or a.join_target_id == aid)
            return max(vals) - min(vals) if vals else 0.0

        # Tier by how long each bus is, shortest held in nearest the boxes: a
        # short run parked out by the frame has to be crossed by every longer
        # one reaching past it, while tucked against the boxes it crosses
        # nothing. Tier 0 lies against the boxes in the head and foot but
        # against the frame down the left margin, so that side counts the other
        # way round. Sorting is stable, so trunks of equal length keep the ICOM
        # order they were grouped in.
        for side in trunk_groups:
            trunk_groups[side] = sorted(trunk_groups[side], key=trunk_run_length,
                                        reverse=(side == 'left'))

        # Calculate tier index for each group and sub-tiers for branches
        for side in trunk_groups:
            roots = trunk_groups[side]
            branch_totals[side] = len(roots)
            for i, rid in enumerate(roots):
                queue = [(rid, 0)] # (id, depth or branch_idx)
                sub_idx = 0
                while queue:
                    curr_id, _ = queue.pop(0)
                    branch_tier_map[curr_id] = i
                    branch_sub_tier_map[curr_id] = sub_idx
                    sub_idx += 1
                    
                    # Find children (both branches and joins contribute to the tree structure)
                    children = [a.id for a in diagram.arrows if a.branch_parent_id == curr_id or a.join_target_id == curr_id]
                    for cid in children:
                        queue.append((cid, sub_idx))
                branch_tree_counts[rid] = sub_idx

        # Pass 1.4: Group branches/joins for horizontal gap distribution (Equidistant Gap Spacing)
        horizontal_gap_groups = {} # (trunk_source_id, subtree_entity_id) -> [arrow_ids]

        def uses_gap_spacing(a, parent):
            """True when this branch's drop is placed by the gap distribution.

            Branches off a vertical bus, or off a boundary Input trunk, get their
            X from the corridor tiers instead and never occupy a slot in the
            box-to-box gap. Counting them here inflated the group size and pushed
            the arrows that *do* cross the gap off its centre line.
            """
            if not parent:
                return False
            if parent.type in [ArrowType.CONTROL, ArrowType.MECHANISM] and \
                    get_parent_source_id(parent, arrow_map) is None:
                return False
            if parent.type == ArrowType.INPUT and parent.source_box_id is None:
                return False
            if a.type not in [ArrowType.INPUT, ArrowType.OUTPUT]:
                return False
            return parent.type in [ArrowType.INPUT, ArrowType.OUTPUT] or \
                get_parent_source_id(parent, arrow_map) is not None

        for a in diagram.arrows:
            # Branches from a trunk
            if a.branch_parent_id:
                parent = arrow_map.get(a.branch_parent_id)
                if uses_gap_spacing(a, parent):
                    key = get_gap_keys(a, is_branch=True)
                    if key not in horizontal_gap_groups: horizontal_gap_groups[key] = []
                    horizontal_gap_groups[key].append(a.id)
            # Joins into a trunk
            if a.join_target_id and a.type in [ArrowType.INPUT, ArrowType.OUTPUT]:
                target = arrow_map.get(a.join_target_id)
                if target:
                    key = get_gap_keys(a, is_branch=False)
                    if key not in horizontal_gap_groups: horizontal_gap_groups[key] = []
                    horizontal_gap_groups[key].append(a.id)
            elif a.join_target_id and a.type == ArrowType.OUTPUT:
                target = arrow_map.get(a.join_target_id)
                if target:
                    key = get_gap_keys(a, is_branch=False)
                    if key not in horizontal_gap_groups: horizontal_gap_groups[key] = []
                    horizontal_gap_groups[key].append(a.id)
        
        # Sort each group for stable ordering
        for key in horizontal_gap_groups:
            group_arrows = [arrow_map[aid] for aid in horizontal_gap_groups[key]]
            group_arrows.sort(key=arrow_sort_key)
            horizontal_gap_groups[key] = [a.id for a in group_arrows]

        # Pass 1.5: Compute lane assignments for forward-flow arrows entering target boxes
        # Group by target box for left-side Input entries, sorting by entry Y position
        # so that higher entry ports get X closer to target box (lane_offset=0)
        # and lower entry ports get X further left (lane_offset=1, 2...), preventing crossings.
        target_input_groups = {}  # target_box_id -> [arrow_ids]
        forward_lane_map = {}     # arrow_id -> lane_offset (int)
        
        for arrow in diagram.arrows:
            if arrow.id in feedback_chains:
                continue
            
            t_id = get_parent_target_id(arrow, arrow_map) or arrow.target_box_id
            if t_id and t_id in box_map:
                if t_id not in target_input_groups:
                    target_input_groups[t_id] = []
                target_input_groups[t_id].append(arrow.id)
        
        for t_id, aids in target_input_groups.items():
            if len(aids) <= 1:
                for aid in aids:
                    forward_lane_map[aid] = 0
                continue
            
            def lane_sort_key(aid):
                return arrow_entry_pos.get(aid, 0)
            
            aids.sort(key=lane_sort_key)
            for i, aid in enumerate(aids):
                forward_lane_map[aid] = i

        # Helper to check if any arrow in a tree connects to a box in the diagram
        def tree_has_box_connection(aid, visited=None):
            if visited is None: visited = set()
            if aid in visited: return False
            visited.add(aid)
            arr = arrow_map.get(aid)
            if not arr: return False
            if (arr.source_box_id and arr.source_box_id in box_map) or (arr.target_box_id and arr.target_box_id in box_map):
                return True
            for child in diagram.arrows:
                if child.branch_parent_id == aid or child.join_target_id == aid:
                    if tree_has_box_connection(child.id, visited):
                        return True
            return False

        # 2. Calculate Arrow Segments (Manhattan Routing)
        for arrow in diagram.arrows:
            source_box = box_map.get(arrow.source_box_id)
            target_box = box_map.get(arrow.target_box_id)
            
            # Special case for unassigned boundary arrows (stubs at edges)
            # An arrow is unassigned if it is a top-level arrow with no box connections in its tree
            is_unassigned = (arrow.branch_parent_id is None and arrow.source_box_id is None and arrow.target_box_id is None and not tree_has_box_connection(arrow.id))
                             
            if is_unassigned:
                stub_length = 50
                
                # Dynamic Shifting: Identify occupied positions to avoid overlaps
                def get_shifted_pos(base_pos, side, used_slots):
                    best_pos = base_pos
                    threshold = 30 # Min distance between stubs and trunks
                    for _ in range(20): # Try shifts
                        conflict = False
                        for upos in used_slots:
                            if abs(best_pos - upos) < threshold:
                                conflict = True
                                break
                        if not conflict: return best_pos
                        best_pos += threshold # Shift by buffer
                    return best_pos

                if arrow.type == ArrowType.INPUT:
                    side = 'left'
                    count = len(boundary_lists[side])
                    idx = boundary_indices[side]
                    boundary_indices[side] += 1
                    base_y = diagram_top + (diagram_bottom - diagram_top) * (idx + 1) / (count + 1)
                    # For inputs, used_slots are arrow_entry/exit positions (Y)
                    used = [v for k, v in arrow_entry_pos.items() if k != arrow.id and arrow_map[k].type in [ArrowType.INPUT, ArrowType.OUTPUT]]
                    y = get_shifted_pos(base_y, side, used)
                    points = [Point(diagram_left, y), Point(diagram_left + stub_length, y)]
                elif arrow.type == ArrowType.CONTROL:
                    side = 'top'
                    count = len(boundary_lists[side])
                    idx = boundary_indices[side]
                    boundary_indices[side] += 1
                    
                    # Respect pre-calculated alignment (sticky to tree)
                    if arrow.id in arrow_exit_pos:
                        x = arrow_exit_pos[arrow.id]
                    else:
                        base_x = diagram_left + (diagram_right - diagram_left) * (idx + 1) / (count + 1)
                        used = [v for k, v in arrow_entry_pos.items() if k != arrow.id and arrow_map[k].type in [ArrowType.CONTROL, ArrowType.MECHANISM]]
                        x = get_shifted_pos(base_x, side, used)
                    points = [Point(x, diagram_top), Point(x, diagram_top + stub_length)]
                elif arrow.type == ArrowType.MECHANISM:
                    side = 'bottom'
                    count = len(boundary_lists[side])
                    idx = boundary_indices[side]
                    boundary_indices[side] += 1
                    
                    # Respect pre-calculated alignment (sticky to tree)
                    if arrow.id in arrow_exit_pos:
                        x = arrow_exit_pos[arrow.id]
                    else:
                        base_x = diagram_left + (diagram_right - diagram_left) * (idx + 1) / (count + 1)
                        used = [v for k, v in arrow_entry_pos.items() if k != arrow.id and arrow_map[k].type in [ArrowType.CONTROL, ArrowType.MECHANISM]]
                        x = get_shifted_pos(base_x, side, used)
                    points = [Point(x, diagram_bottom), Point(x, diagram_bottom - stub_length)]
                elif arrow.type == ArrowType.OUTPUT:
                    side = 'right'
                    count = len(boundary_lists[side])
                    idx = boundary_indices[side]
                    boundary_indices[side] += 1
                    base_y = diagram_top + (diagram_bottom - diagram_top) * (idx + 1) / (count + 1)
                    used = [v for k, v in arrow_entry_pos.items() if k != arrow.id and arrow_map[k].type in [ArrowType.INPUT, ArrowType.OUTPUT]]
                    y = get_shifted_pos(base_y, side, used)
                    # For unassigned stubs, always use a uniform length stub instead of a dynamic trunk position
                    tx = diagram_right - stub_length
                    points = [Point(tx, y), Point(diagram_right, y)]
                else:
                    points = [Point(diagram_left, diagram_top), Point(diagram_left + 10, diagram_top + 10)]
                
                arrow.segments = points
            else:
                # if not arrow.segments: # This check is removed as segments are always calculated here
                    start_x, start_y, start_dir = 0, 0, "right"
                    
                    if arrow.branch_parent_id:
                        # BRANCHING LOGIC
                        parent = arrow_map.get(arrow.branch_parent_id)
                        if parent:
                            # 1. Sticky Parent Position
                            parent_pos = arrow_exit_pos.get(parent.id) or arrow_entry_pos.get(parent.id)
                            is_parent_vertical = (parent.type in [ArrowType.CONTROL, ArrowType.MECHANISM] and get_parent_source_id(parent, arrow_map) is None)
                            # Only use boundary tier logic for true boundary arrows (no source box).
                            # Box-to-box INPUT parents (e.g. P.2.1 from A41→A42) use gap-spacing instead.
                            is_parent_boundary_input = (parent.type == ArrowType.INPUT and parent.source_box_id is None)
                            if is_parent_vertical or is_parent_boundary_input:
                                # Determine Junction Base Coordinates (Sticky to parent path)
                                # Parent position is Y if horizontal, X if vertical
                                if is_parent_vertical:
                                    j_x = parent_pos if parent_pos is not None else (arrow.junction_point.x if arrow.junction_point else 0)
                                    j_y = arrow.junction_point.y if arrow.junction_point else 0
                                else: # INPUT boundary
                                    # Parent position is Y (best_y) for INPUT
                                    j_y = parent_pos if parent_pos is not None else (arrow.junction_point.y if arrow.junction_point else 0)
                                    j_x = arrow.junction_point.x if arrow.junction_point else 0

                                # Force Tier using dynamic equidistant spacing
                                tier_idx = branch_tier_map.get(arrow.id, 0)
                                rid = get_root_id(arrow.id)
                                
                                if is_parent_vertical and parent.type == ArrowType.CONTROL:
                                    tier_step = head_live_span / (branch_totals['top'] + 1)
                                    start_y = head_live_max - (tier_step * (tier_idx + 1))
                                    start_x = j_x
                                elif is_parent_vertical and parent.type == ArrowType.MECHANISM: # MECHANISM
                                    tier_step = foot_live_span / (branch_totals['bottom'] + 1)
                                    start_y = foot_live_min + (tier_step * (tier_idx + 1))
                                    start_x = j_x
                                else: # INPUT boundary
                                    tier_step = left_live_span / (branch_totals['left'] + 1)
                                    start_x = left_live_min + (tier_step * (tier_idx + 1))
                                    start_y = j_y
                                    
                            # 3. Input/Output Arrows (Horizontal Tiers / Gap Spacing)
                            else:
                                if parent.type in [ArrowType.INPUT, ArrowType.OUTPUT] or get_parent_source_id(parent, arrow_map) is not None:
                                    # Horizontal Trunk -> Branch
                                    
                                    # 3. Identify all branches sharing this "Gap" (Source to Target)
                                    s_id, t_id = get_gap_keys(arrow, is_branch=True)
                                    
                                    # 1. Define Gap Start (Root Trunk Source)
                                    if parent and parent.source_box_id and parent.source_box_id in box_map:
                                        p_src_box = box_map[parent.source_box_id]
                                        trunk_start_x = p_src_box.x + p_src_box.width
                                        idx = arrow_exit_index.get(parent.id, 0)
                                        cnt = exit_counts.get(p_src_box.id, {}).get('right', 1)
                                        start_y = p_src_box.y + get_equidistant_position(p_src_box, 'right', idx, cnt)
                                    elif s_id and s_id in box_map:
                                        trunk_start_x = box_map[s_id].x + box_map[s_id].width
                                        start_y = parent_pos if parent_pos is not None else target_box.y
                                    else:
                                        trunk_start_x = diagram_left # For Input Trunks
                                        start_y = parent_pos if parent_pos is not None else target_box.y

                                    # 2. Define Gap End (Target Box Left)
                                    if target_box:
                                        gap_end_x = target_box.x
                                    else:
                                        gap_end_x = diagram_right

                                    is_box_to_box_parent = bool(parent and parent.source_box_id and parent.target_box_id and parent.source_box_id in box_map and parent.target_box_id in box_map)

                                    if is_box_to_box_parent:
                                        # If parent trunk connects to a target box (e.g. P.2.1 to A42), the parent trunk only spans up to parent's target box!
                                        p_target_box = box_map[parent.target_box_id]
                                        if p_target_box.x > trunk_start_x:
                                            gap_end_x = min(gap_end_x, p_target_box.x)
                                    else:
                                        # For boundary trunks spanning across diagram, keep junction in immediate gap before target_box
                                        if target_box:
                                            prev_boxes = [b for b in box_map.values() if b.x + b.width <= target_box.x]
                                            if prev_boxes:
                                                max_prev_right = max(b.x + b.width for b in prev_boxes)
                                                trunk_start_x = max(trunk_start_x, max_prev_right)
                                    
                                    if arrow.type in [ArrowType.CONTROL, ArrowType.MECHANISM] and arrow.target_box_id and arrow.target_box_id in box_map:
                                        t_box = box_map[arrow.target_box_id]
                                        idx = arrow_entry_index.get(arrow.id, 0)
                                        side = 'top' if arrow.type == ArrowType.CONTROL else 'bottom'
                                        total = entry_counts.get(t_box.id, {}).get(side, 0)
                                        start_x = t_box.x + get_equidistant_position(t_box, side, idx, total)
                                        start_y = arrow_exit_pos.get(parent.id) if (parent and parent.source_box_id) else (parent_pos if parent_pos is not None else target_box.y)
                                    elif parent.type in [ArrowType.INPUT, ArrowType.OUTPUT] and arrow.type in [ArrowType.INPUT, ArrowType.OUTPUT]:
                                        # Share the corridor with every other arrow crossing the
                                        # same box-to-box gap, not just siblings of one parent.
                                        # horizontal_gap_groups is keyed by (source box, target box);
                                        # keying the lookup on parent.id instead missed every time,
                                        # so each arrow saw a group of one and took the midpoint -
                                        # which is why unrelated drops landed on the same X.
                                        key = (s_id, t_id)
                                        group = horizontal_gap_groups.get(key, [arrow.id])
                                        count = len(group)
                                        sub_idx = group.index(arrow.id) if arrow.id in group else 0

                                        
                                        # 4. Calculate Dynamic Equidistant Distribution
                                        if gap_end_x > trunk_start_x:
                                            gap_width = gap_end_x - trunk_start_x
                                            start_x = trunk_start_x + (gap_width * (sub_idx + 1) / (count + 1))
                                        else:
                                            start_x = trunk_start_x + 50 + (sub_idx * 20)
                                        
                                        if 'start_y' not in locals() or start_y is None:
                                            start_y = arrow_exit_pos.get(parent.id) if (parent and parent.source_box_id) else (parent_pos if parent_pos is not None else target_box.y)
                                    elif arrow.join_target_id:
                                        pass
                                    else:
                                        start_x = parent_pos if parent_pos is not None else (arrow.junction_point.x if arrow.junction_point else 0)
                                        start_y = arrow.junction_point.y if arrow.junction_point else 0
                            
                            # CRITICAL PERSISTENCE FIX: UNCONDITIONALLY Save Calculated Junction Point
                            # This ensures that even if 'Auto Route' cleared it, it gets saved now.
                            arrow.junction_point = Point(start_x, start_y)
                            
                            if arrow.junction_point not in parent.branch_points:
                                parent.branch_points.append(arrow.junction_point)
                                
                            # Direction
                            is_parent_vertical = (parent.type in [ArrowType.CONTROL, ArrowType.MECHANISM] and get_parent_source_id(parent, arrow_map) is None)
                            if is_parent_vertical:
                                # Tapping a vertical trunk/bus: start horizontal (right/left) to reach the target X
                                # before turning vertical into the box. This creates the 'shared trunk' look.
                                start_dir = "right" if (target_box and target_box.x > start_x) else "left"
                            elif parent.type in [ArrowType.INPUT, ArrowType.OUTPUT] or get_parent_source_id(parent, arrow_map) is not None:
                                # Dropping from a horizontal trunk (visual bus at tier_x/tier_y)
                                if arrow.type in [ArrowType.CONTROL, ArrowType.MECHANISM]:
                                    # Target is vertical port (top/bottom): run horizontally first
                                    start_dir = "left" if (target_box and target_box.x < start_x) else "right"
                                else:
                                    # Target is horizontal port (input/left): start vertically to reach target_box.Y,
                                    # unless target_box is further to the right in another column, or is a feedback loop!
                                    is_f_arrow = arrow.id in feedback_chains
                                    # Running right first is only worth it when the
                                    # lane at start_y is actually clear. If a box sits
                                    # on it, the router has to duck around that box and
                                    # the drop lands wherever the detour allows instead
                                    # of in its own corridor lane - so drop first.
                                    lane_clear = True
                                    if target_box:
                                        x_lo = min(start_x, target_box.x)
                                        x_hi = max(start_x, target_box.x)
                                        lane_clear = not any(
                                            b.x < x_hi and b.x + b.width > x_lo and
                                            b.y < start_y < b.y + b.height
                                            for b in diagram.boxes)
                                    if is_f_arrow or (target_box and target_box.x > start_x + 150 and lane_clear):
                                        start_dir = "right"
                                    else:
                                        start_dir = "bottom" if (target_box and target_box.y > start_y) else "top"

                            else:
                                start_dir = "right"
                                
                    elif source_box:
                        side = 'right'
                        idx = arrow_exit_index.get(arrow.id, 0)
                        start_x = source_box.x + source_box.width
                        start_y = source_box.y + get_equidistant_position(source_box, side, idx, exit_counts[source_box.id][side])
                        start_dir = "right"
                    else:
                        # External Source (Boundary Arrow)
                        if arrow.target_box_id:
                            idx = arrow_entry_index.get(arrow.id, 0)
                            if arrow.type == ArrowType.INPUT:
                                side = 'left'
                                start_x = diagram_left
                                entry_y = arrow_entry_pos.get(arrow.id)
                                start_y = entry_y if entry_y is not None else ((target_box.y + get_equidistant_position(target_box, side, idx, entry_counts[target_box.id][side])) if target_box else (diagram_top + diagram_bottom) / 2)
                                start_dir = "right"
                            elif arrow.type == ArrowType.CONTROL:
                                side = 'top'
                                exit_x = arrow_exit_pos.get(arrow.id)
                                start_x = exit_x if exit_x is not None else ((target_box.x + get_equidistant_position(target_box, side, idx, entry_counts[target_box.id][side])) if target_box else (diagram_left + diagram_right) / 2)
                                start_y = diagram_top
                                start_dir = "bottom"
                            elif arrow.type == ArrowType.MECHANISM:
                                side = 'bottom'
                                exit_x = arrow_exit_pos.get(arrow.id)
                                start_x = exit_x if exit_x is not None else ((target_box.x + get_equidistant_position(target_box, side, idx, entry_counts[target_box.id][side])) if target_box else (diagram_left + diagram_right) / 2)
                                start_y = diagram_bottom
                                start_dir = "top"
                            else:
                                exit_x = arrow_exit_pos.get(arrow.id)
                                start_x = exit_x if exit_x is not None else diagram_left
                                start_y = (target_box.y + target_box.height/2) if target_box else (diagram_top + diagram_bottom) / 2
                                start_dir = "right"
                        else:
                            # External Source with no Target Box (Trunk/Bus)
                            if arrow.type == ArrowType.CONTROL:
                                start_x = arrow_exit_pos.get(arrow.id, (diagram_left + diagram_right) / 2)
                                start_y = diagram_top
                                start_dir = "bottom"
                            elif arrow.type == ArrowType.MECHANISM:
                                start_x = arrow_exit_pos.get(arrow.id, (diagram_left + diagram_right) / 2)
                                start_y = diagram_bottom
                                start_dir = "top"
                            elif arrow.type == ArrowType.OUTPUT:
                                # Use dynamic tier X coordinate for the vertical trunk
                                start_x = output_trunk_x_map.get(arrow.id, diagram_right - 50)
                                start_y = arrow_exit_pos.get(arrow.id, (diagram_top + diagram_bottom) / 2)
                                start_dir = "right"
                            else: # INPUT
                                start_x = diagram_left
                                start_y = arrow_exit_pos.get(arrow.id, (diagram_top + diagram_bottom) / 2)
                                start_dir = "right"
        
                    # 2. Determine End Point and Direction (Approach)
                    target_pos = None
                    
                    # CRITICAL FEEDBACK INTEGRATION: Bypass ALL snapping/merging logic logic for feedback.
                    # This ensures feedback loops (Rank 2) always use their dedicated port slots.
                    is_feedback = arrow.id in feedback_chains
                    if arrow.join_target_id and not is_feedback:
                        target_arrow = arrow_map.get(arrow.join_target_id)
                        if target_arrow:
                            target_pos = arrow_exit_pos.get(target_arrow.id) or arrow_entry_pos.get(target_arrow.id)
                            is_horiz_trunk = (target_arrow.type in [ArrowType.INPUT, ArrowType.OUTPUT])
                            
                            if is_horiz_trunk:
                                # Logic to find the x-junction in the gap
                                s_id, t_id = get_gap_keys(arrow, is_branch=False)
                                
                                # Gap boundaries
                                if s_id and s_id in box_map: trunk_start_x = box_map[s_id].x + box_map[s_id].width
                                else: trunk_start_x = diagram_left
                                
                                if target_box: gap_end_x = target_box.x
                                elif t_id and t_id in box_map: gap_end_x = box_map[t_id].x
                                else: gap_end_x = diagram_right

                                # TIERED OUTPUT MERGE: Route joiner to trunk's vertical bus
                                if arrow.type == ArrowType.OUTPUT and not target_box:
                                    # Output joiners route to trunk_x at the trunk's Y level
                                    root_tid = get_root_trunk_id(arrow, arrow_map)
                                    end_x = output_merge_x_map.get(arrow.id, output_trunk_x_map.get(root_tid, output_trunk_x_map.get(target_arrow.id, diagram_right - 50)))
                                    # Route to trunk's Y level so manhattan router creates L-bend merge
                                    trunk_y = target_pos
                                    if trunk_y is None and target_arrow.source_box_id and target_arrow.source_box_id in box_map:
                                        tb = box_map[target_arrow.source_box_id]
                                        t_idx = arrow_exit_index.get(target_arrow.id, 0)
                                        t_cnt = exit_counts.get(tb.id, {}).get('right', 1)
                                        trunk_y = tb.y + get_equidistant_position(tb, 'right', t_idx, t_cnt)
                                    if trunk_y is None:
                                        trunk_y = start_y
                                    end_y = trunk_y
                                    end_dir = "bottom" if start_y > end_y else ("top" if start_y < end_y else "left")
                                else:
                                    # Standard Gap Spacing (Internal Box-to-Box or Input)
                                    key = (s_id, t_id)
                                    group = horizontal_gap_groups.get(key, [arrow.id])
                                    count = len(group)
                                    sub_idx = group.index(arrow.id) if arrow.id in group else 0
                                    
                                    if gap_end_x > trunk_start_x:
                                        end_x = trunk_start_x + (gap_end_x - trunk_start_x) * (sub_idx + 1) / (count + 1)
                                    else:
                                        end_x = trunk_start_x + 50 + (sub_idx * 20)

                                    end_y = target_pos if target_pos is not None else 500
                                    # Force orthogonal intersection tip markers
                                    # If we are below the trunk (y > end_y), we enter the BOTTOM of the trunk.
                                    end_dir = "bottom" if start_y > end_y else "top"
                            else: # Vertical Trunk
                                end_x = target_pos if target_pos is not None else 500
                                if target_arrow.type == ArrowType.CONTROL:
                                    end_y = arrow.junction_point.y if arrow.junction_point else start_y + 100
                                else: # MECHANISM
                                    end_y = arrow.junction_point.y if arrow.junction_point else start_y - 100
                                end_dir = "left" if start_x < end_x else "right"
                                
                            arrow.junction_point = Point(end_x, end_y)
                            if arrow.junction_point not in target_arrow.join_points:
                                target_arrow.join_points.append(arrow.junction_point)
                        else:
                            end_x, end_y, end_dir = 500, 500, "left"
                            
                    elif target_box or is_feedback:
                        # Feedback always targets a box eventually, resolve surgically if needed
                        t_box = target_box
                        if is_feedback and not t_box and arrow.join_target_id:
                             tgt = arrow_map.get(arrow.join_target_id)
                             if tgt: t_box = box_map.get(tgt.target_box_id)
                        
                        idx = arrow_entry_index.get(arrow.id)
                        if idx is not None and t_box:
                            if arrow.type == ArrowType.INPUT:
                                side = 'left'
                                end_x = t_box.x
                                end_y = t_box.y + get_equidistant_position(t_box, side, idx, entry_counts[t_box.id][side])
                                end_dir = "left"
                            elif arrow.type == ArrowType.CONTROL:
                                side = 'top'
                                end_x = t_box.x + get_equidistant_position(t_box, side, idx, entry_counts[t_box.id][side])
                                end_y = t_box.y
                                end_dir = "top"
                            elif arrow.type == ArrowType.MECHANISM:
                                side = 'bottom'
                                end_x = t_box.x + get_equidistant_position(t_box, side, idx, entry_counts[t_box.id][side])
                                end_y = t_box.y + t_box.height
                                end_dir = "bottom"
                        else:
                            # Final fallback
                            end_x, end_y = (target_box.x if target_box else 500), (target_box.y + 50 if target_box else 500)
                            end_dir = "left"
                    else: # External Target
                        if arrow.id in trunk_ids:
                            # This is a trunk with no target box. Extend to furthest junction.
                            if arrow.type == ArrowType.OUTPUT:
                                child_arrows = [a for a in diagram.arrows if a.join_target_id == arrow.id and (a.source_box_id in box_map or a.target_box_id in box_map)]
                            else:
                                child_arrows = [a for a in diagram.arrows if a.branch_parent_id == arrow.id and (a.source_box_id in box_map or a.target_box_id in box_map)]
                            if child_arrows:
                                if arrow.type in [ArrowType.CONTROL, ArrowType.MECHANISM, ArrowType.INPUT]:
                                    tier_idx = branch_tier_map.get(arrow.id, 0)
                                    if arrow.type == ArrowType.CONTROL:
                                        tier_step = head_live_span / (branch_totals['top'] + 1)
                                        end_y = head_live_max - (tier_step * (tier_idx + 1))
                                    elif arrow.type == ArrowType.MECHANISM:
                                        tier_step = foot_live_span / (branch_totals['bottom'] + 1)
                                        end_y = foot_live_min + (tier_step * (tier_idx + 1))
                                    elif arrow.type == ArrowType.INPUT:
                                        tier_step = left_live_span / (branch_totals['left'] + 1)
                                        end_x = left_live_min + (tier_step * (tier_idx + 1))
                                    
                                    if arrow.type in [ArrowType.CONTROL, ArrowType.MECHANISM]:
                                        # Find the furthest intended branch position using Pass 1 entry coordinates
                                        child_xs = [arrow_entry_pos.get(c.id, start_x) for c in child_arrows]
                                        furthest_x = max(child_xs) if (abs(max(child_xs) - start_x) > abs(min(child_xs) - start_x)) else min(child_xs)
                                        end_x = furthest_x
                                        end_dir = "right" if end_x >= start_x else "left"
                                    elif arrow.type == ArrowType.INPUT:
                                        # Vertical bus dropping across Y coordinates
                                        child_ys = [arrow_entry_pos.get(c.id, start_y) for c in child_arrows]
                                        furthest_y = max(child_ys) if (abs(max(child_ys) - start_y) > abs(min(child_ys) - start_y)) else min(child_ys)
                                        end_y = furthest_y
                                        end_dir = "bottom" if end_y >= start_y else "top"
                                elif arrow.type == ArrowType.OUTPUT:
                                    # Output Bus joining across Y coordinates
                                    child_ys = [arrow_entry_pos.get(c.id, start_y) for c in child_arrows]
                                    furthest_y = max(child_ys) if (abs(max(child_ys) - start_y) > abs(min(child_ys) - start_y)) else min(child_ys)
                                    
                                    max_box_right = max(b.x + b.width for b in diagram.boxes) if diagram.boxes else diagram_right - 100
                                    safe_trunk_x = max(max_box_right + 40, diagram_right - 50)
                                    trunk_x = output_trunk_x_map.get(arrow.id, safe_trunk_x)
                                    
                                    # Store junction merge points for all joiner children at trunk_x
                                    for c in child_arrows:
                                        c_y = arrow_entry_pos.get(c.id, start_y)
                                        c.junction_point = Point(trunk_x, c_y)
                                        if c.junction_point not in arrow.join_points:
                                            arrow.join_points.append(c.junction_point)
                                            
                                    v_junc = Point(trunk_x, furthest_y)
                                    if v_junc not in arrow.join_points:
                                        arrow.join_points.append(v_junc)
                                        
                                    if arrow.source_box_id is None:
                                        # Pure boundary trunk (no source box): span vertical bus from furthest_y to exit
                                        original_start_y = start_y
                                        start_y = furthest_y
                                        start_dir = "top" if furthest_y > original_start_y else ("bottom" if furthest_y < original_start_y else "right")
                                        end_x = diagram_right
                                        end_y = original_start_y
                                    else:
                                        # Box-connected trunk (e.g. A43): route straight right from box to diagram_right
                                        end_x = diagram_right
                                        end_y = start_y

                                    end_dir = "right"
                                    route_padding = 0
                                else:
                                    # Fallback (including Output if no children)
                                    end_x, end_y, end_dir = diagram_right, start_y, "right"
                            else:
                                # COMPLETELY ORPHANED BOUNDARY ARROW (Synchronized from Parent, no boxes yet)
                                # This ensures that IDs like P.2 are always visible even before assignment.
                                if arrow.type == ArrowType.OUTPUT:
                                    end_x, end_y, end_dir = diagram_right, start_y, "right"
                                elif arrow.type == ArrowType.INPUT:
                                    end_x, end_y, end_dir = start_x + 50, start_y, "right"
                                elif arrow.type == ArrowType.CONTROL:
                                    end_x, end_y, end_dir = start_x, start_y + 50, "bottom"
                                else: # MECHANISM
                                    end_x, end_y, end_dir = start_x, start_y - 50, "top"
                        elif arrow.join_target_id:
                            # RESPECT THE JOINER JUNCTION: Use the pre-calculated merge point
                            target_arrow = arrow_map.get(arrow.join_target_id)
                            if arrow.type == ArrowType.OUTPUT and target_arrow:
                                max_box_right = max(b.x + b.width for b in diagram.boxes) if diagram.boxes else diagram_right - 100
                                safe_trunk_x = max(max_box_right + 40, diagram_right - 50)
                                trunk_x = output_trunk_x_map.get(target_arrow.id, safe_trunk_x)
                                end_x = trunk_x
                                target_y = arrow_exit_pos.get(target_arrow.id)
                                if target_y is None and target_arrow.source_box_id in box_map:
                                    tb = box_map[target_arrow.source_box_id]
                                    idx = arrow_exit_index.get(target_arrow.id, 0)
                                    cnt = exit_counts.get(tb.id, {}).get('right', 1)
                                    target_y = tb.y + get_equidistant_position(tb, 'right', idx, cnt)
                                if target_y is None:
                                    sib = next((a for a in diagram.arrows if a.id != arrow.id and (a.id == target_arrow.id or a.join_target_id == target_arrow.id) and a.source_box_id in box_map), None)
                                    if sib and sib.source_box_id in box_map:
                                        tb = box_map[sib.source_box_id]
                                        idx = arrow_exit_index.get(sib.id, 0)
                                        cnt = exit_counts.get(tb.id, {}).get('right', 1)
                                        target_y = tb.y + get_equidistant_position(tb, 'right', idx, cnt)
                                if target_y is None:
                                    target_y = start_y
                                end_y = target_y
                            elif arrow.junction_point:
                                end_x = arrow.junction_point.x
                                end_y = arrow.junction_point.y
                            else:
                                if target_arrow:
                                    end_x = right_live_min + 40 if arrow.type == ArrowType.OUTPUT else diagram_left + 40
                                    tp = arrow_exit_pos.get(target_arrow.id)
                                    end_y = tp if tp is not None else 500
                                else:
                                    end_x, end_y = 500, 500
                            
                            # Correct end direction for the L-bend (approach moving UP if start_y > end_y)
                            end_dir = "top" if start_y > end_y else "bottom"
                        else:
                            # Arrow is not a trunk, not a joiner, and has no target box
                            if arrow.type == ArrowType.OUTPUT:
                                end_x = diagram_right
                                end_y = start_y
                                end_dir = "right"
                            else:
                                end_x, end_y, end_dir = 500, 500, "left"

                        # arrow_exit_pos[arrow.id] = (end_x, end_y, end_dir) # REMOVED: DESTRICTIVE TUPLE ASSIGNMENT
                    
                    # Include all boxes as obstacles so feedback loops properly route around the source and target boxes!
                    obstacles = diagram.boxes

                    # NEW: Deterministic Staggering usage
                    f_salt = feedback_salts.get(arrow.id, 0)

                    # Minimize padding for branches and joins to prevent zigzags/S-curves at tapping points
                    route_padding = 0 if (arrow.branch_parent_id or arrow.join_target_id) else 20
                    
                    routing_type = arrow.type.value
                    if arrow.join_target_id:
                        target_arr = arrow_map.get(arrow.join_target_id)
                        if target_arr: routing_type = target_arr.type.value
                    points = manhattan_route((start_x, start_y), (end_x, end_y), start_dir, end_dir, obstacles, routing_type, padding=route_padding, salt=f_salt, lane_offset=forward_lane_map.get(arrow.id, 0))
                    arrow.segments = points
                
        # Pass 2: Calculate arrow depth for Z-Ordering (Roots on Top to mask branch overlaps)
        arrow_depths = {a.id: 0 for a in diagram.arrows}
        changed = True
        while changed:
            changed = False
            for a in diagram.arrows:
                # Children are arrows that branch FROM or join INTO this arrow
                child_ids = [c.id for c in diagram.arrows if c.branch_parent_id == a.id or c.join_target_id == a.id]
                if child_ids:
                    new_depth = max(arrow_depths[cid] for cid in child_ids) + 1
                    if arrow_depths[a.id] < new_depth:
                        arrow_depths[a.id] = new_depth
                        changed = True

        # Pass 2a: Pull apart parallel runs of different signals that landed on
        # top of each other despite having room in their corridor.
        separate_parallel_runs(diagram, arrow_map)

        # Pass 2a.2: Now share every corridor out evenly. The router places each
        # line from a local rule and cannot see what else ended up in the same
        # band, so this is the only point where the whole channel is visible.
        equalise_corridor_lanes(diagram,
                                (diagram_left, diagram_right),
                                (diagram_top, diagram_bottom))

        # Pass 2b: Normalise every arrow BEFORE any junction geometry is derived.
        # Junction repair compares one arrow's tap against another arrow's
        # segments, so all of them have to be in their final form first.
        for arrow in diagram.arrows:
            # Double pass ensures snapping doesn't create new duplicate points
            arrow.segments = simplify_path(arrow.segments)
            for p in arrow.segments:
                p.x = round(p.x)
                p.y = round(p.y)
            arrow.segments = simplify_path(arrow.segments)
            if not arrow.segments:
                # FALLBACK: Ensure newly synced boundary trunks (orphaned) are visible
                start_pt = Point(*arrow_entry_pos.get(arrow.id, (0, 0, "right"))[:2])
                end_pt = Point(*arrow_exit_pos.get(arrow.id, (500, 500, "right"))[:2])
                arrow.segments = [start_pt, end_pt]

        # Pass 2b.1: The lane sharing above moves drop lanes without moving the
        # taps that feed them, so a branch can be left hooking back along its
        # trunk. Straighten those now the lanes are final.
        _straighten_backward_taps(diagram, arrow_map)

        # Pass 2c: Pull branch/join endpoints onto material their host actually
        # draws, so no tap is left stranded on a corner the rounding cut away.
        merge_radius = JUNCTION_RADIUS
        junction_hosts = snap_junction_endpoints(diagram, arrow_map, merge_radius)

        # 3. Draw Items (with rounded aesthetics)
        # Separate calculation from drawing to ensure parent segments exist for rounding
        for arrow in diagram.arrows:
            points = arrow.segments
            if not points:
                # FALLBACK: Ensure newly synced boundary trunks (orphaned) are visible
                start_pt = Point(*arrow_entry_pos.get(arrow.id, (0, 0, "right"))[:2])
                end_pt = Point(*arrow_exit_pos.get(arrow.id, (500, 500, "right"))[:2])
                if start_pt and end_pt:
                    arrow.segments = [start_pt, end_pt]
                    points = arrow.segments
                else:
                    continue
            
            # Add runway points so make_rounded_path() sweeps each junction into
            # a smooth curve. Only perpendicular (T-shaped) taps need one: a child
            # that runs *along* its host has no corner to round, and inventing a
            # runway for it just produces a stub poking past the trunk.
            extended_points = list(points)

            branch_ref = junction_hosts.get((arrow.id, 'branch'))
            join_ref = junction_hosts.get((arrow.id, 'join'))

            did_prepend = False
            if branch_ref and not branch_ref['parallel']:
                ext_pt = junction_runway_point(arrow, 'branch', branch_ref, merge_radius)
                if ext_pt is not None:
                    extended_points.insert(0, ext_pt)
                    did_prepend = True

            did_append = False
            if join_ref and not join_ref['parallel']:
                ext_pt = junction_runway_point(arrow, 'join', join_ref, merge_radius)
                if ext_pt is not None:
                    extended_points.append(ext_pt)
                    did_append = True



            # Determine if any child branches or joins at the start/end points of this trunk
            trunk_skip_start = False
            trunk_skip_end = False
            for c in diagram.arrows:
                if c.id == arrow.id:
                    continue
                is_child = (c.join_target_id == arrow.id) or (c.branch_parent_id == arrow.id)
                if is_child:
                    if c.segments:
                        for idx, p in enumerate(c.segments):
                            if abs(p.x - points[0].x) < 2 and abs(p.y - points[0].y) < 2:
                                is_turn = True
                                if idx == 0 and len(c.segments) >= 2 and len(points) >= 2:
                                    v_child = Point(c.segments[1].x - p.x, c.segments[1].y - p.y)
                                    v_parent = Point(points[1].x - p.x, points[1].y - p.y)
                                    is_turn = (v_child.x == 0) != (v_parent.x == 0)
                                elif idx == len(c.segments) - 1 and len(c.segments) >= 2 and len(points) >= 2:
                                    v_child = Point(p.x - c.segments[-2].x, p.y - c.segments[-2].y)
                                    v_parent = Point(points[1].x - p.x, points[1].y - p.y)
                                    is_turn = (v_child.x == 0) != (v_parent.x == 0)
                                if is_turn:
                                    trunk_skip_start = True
                            
                            if abs(p.x - points[-1].x) < 2 and abs(p.y - points[-1].y) < 2:
                                is_turn = True
                                if idx == 0 and len(c.segments) >= 2 and len(points) >= 2:
                                    v_child = Point(c.segments[1].x - p.x, c.segments[1].y - p.y)
                                    v_parent = Point(p.x - points[-2].x, p.y - points[-2].y)
                                    is_turn = (v_child.x == 0) != (v_parent.x == 0)
                                elif idx == len(c.segments) - 1 and len(c.segments) >= 2 and len(points) >= 2:
                                    v_child = Point(p.x - c.segments[-2].x, p.y - c.segments[-2].y)
                                    v_parent = Point(p.x - points[-2].x, p.y - points[-2].y)
                                    is_turn = (v_child.x == 0) != (v_parent.x == 0)
                                if is_turn:
                                    trunk_skip_end = True
                    elif c.junction_point:
                        if abs(c.junction_point.x - points[0].x) < 2 and abs(c.junction_point.y - points[0].y) < 2:
                            trunk_skip_start = True
                        if abs(c.junction_point.x - points[-1].x) < 2 and abs(c.junction_point.y - points[-1].y) < 2:
                            trunk_skip_end = True

            # Determine if this arrow should have a head.
            # 1. Joins never have heads (they merge into a bus).
            # 2. Boundary outputs always have heads.
            # 3. Trunks (input/control/mechanism buses) with no target box never
            #    have heads - they terminate at the last branch.
            # Force visibility for unassigned boundary signals to show signal direction.
            is_trunk_only = (arrow.id in trunk_ids and arrow.target_box_id is None)
            is_un_stub = (arrow.source_box_id is None and arrow.target_box_id is None and not tree_has_box_connection(arrow.id))

            if arrow.join_target_id:
                has_head_visual = False # Suppress for joiners
            elif arrow.type == ArrowType.OUTPUT and arrow.target_box_id is None:
                has_head_visual = True # ALWAYS show for boundary output trunks
            elif is_un_stub:
                has_head_visual = True # ALWAYS show for orphaned stubs
            else:
                has_head_visual = not is_trunk_only

            # Shorten the trunk's extended_points directly at drawing-level if a child is at the extremity
            # (Only shorten endpoints/starts if a child turns at that extremity, to prevent air gaps at collinear continuations and boundary entries)
            if trunk_skip_start and not arrow.branch_parent_id and len(points) >= 2:
                p0, p1 = points[0], points[1]
                dx, dy = p1.x - p0.x, p1.y - p0.y
                dist = (dx*dx + dy*dy)**0.5
                if dist > 10:
                    extended_points[0] = Point(p0.x + (dx/dist)*10, p0.y + (dy/dist)*10)

            # Never pull back a tip that carries an arrowhead: the head is drawn at
            # the true endpoint, so shortening the line there opens a gap behind it.
            if trunk_skip_end and not arrow.join_target_id and not has_head_visual and len(points) >= 2:
                p_pen, p_last = points[-2], points[-1]
                dx, dy = p_last.x - p_pen.x, p_last.y - p_pen.y
                dist = (dx*dx + dy*dy)**0.5
                if dist > 10:
                    extended_points[-1] = Point(p_last.x - (dx/dist)*10, p_last.y - (dy/dist)*10)

            # A branch must NOT suppress its opening run: make_rounded_path has to
            # draw the runway along the trunk for the merge to curve out of it.
            # A join's runway, by contrast, IS the trunk, so drawing it again would
            # double the line - skip_end stops the path at the end of the arc.
            skip_s = False
            skip_e = did_append

            path = make_rounded_path(extended_points, radius=merge_radius, skip_start=skip_s, skip_end=skip_e)

            arrow_item = ArrowItem(
                path, 
                tunnel_source=arrow.tunnel_source, 
                tunnel_target=arrow.tunnel_target,
                branch_points=arrow.branch_points,
                join_points=arrow.join_points,
                has_head=has_head_visual,
                arrow_id=arrow.id,
                arrow_data=arrow,
                radius=merge_radius
            )
            self.addItem(arrow_item)
            
            # Preserve the calculated extended segments and skip properties for redraws
            arrow_item.extended_segments = extended_points
            arrow_item.skip_start = skip_s
            arrow_item.skip_end = skip_e
            
            # Use Hierarchy for Z-Order: Roots (buses) on top of branches
            arrow_item.setZValue(10 + arrow_depths[arrow.id])
            
            # Apply Style
            arrow_item.set_style_properties(
                color=QColor(arrow.color),
                thickness=arrow.thickness,
                style_name=arrow.style
            )
            
            # Apply font properties from model
            arrow_item.set_label_font_family(arrow.label_font_family)
            arrow_item.set_label_font_size(arrow.label_font_size)
            arrow_item.set_label_font_bold(arrow.label_font_bold)
            arrow_item.set_label_font_italic(arrow.label_font_italic)
            
            # Label Visibility: Only show label on the primary Trunk (boundary or box-to-box)
            # This keeps signal buses clean by not labeling every individual stub branch.
            if arrow.branch_parent_id or arrow.join_target_id:
                # For branches/joins: if specialized (non-redundant), label should be
                # near the connected box. If redundant, label will be suppressed anyway.
                if arrow.target_box_id:
                    # Branch going INTO a box — place label near end (the box)
                    arrow_item.set_label(arrow.label, percent=0.85)
                elif arrow.source_box_id:
                    # Join coming FROM a box — place label near start (the box)
                    arrow_item.set_label(arrow.label, percent=0.15)
                else:
                    arrow_item.set_label(arrow.label, percent=0.5)
            else:
                # Independent trunk arrows
                if arrow.source_box_id and arrow.target_box_id:
                    # Box-to-box arrow — label in middle
                    arrow_item.set_label(arrow.label, percent=0.5)
                elif arrow.source_box_id and not arrow.target_box_id:
                    # Source box to boundary — label near the source box (start)
                    arrow_item.set_label(arrow.label, percent=0.15)
                elif not arrow.source_box_id and arrow.target_box_id:
                    # Boundary to target box — label near boundary (start)
                    arrow_item.set_label(arrow.label, percent=0.02)
                else:
                    # Pure boundary stub (no boxes) — at boundary edge
                    if arrow.type == ArrowType.OUTPUT:
                        arrow_item.set_label(arrow.label, percent=0.98)
                    else:
                        arrow_item.set_label(arrow.label, percent=0.02)
            
            # Set initial show_id state from main window if possible
            # We can check a property on the scene or pass it.
            # For now, we'll assume default OFF, but MainWindow.toggle_arrow_ids will fix it.

        # Second pass over arrow items to update label displays after all items are added to the scene
        arrow_items = [item for item in self.items() if isinstance(item, ArrowItem)]
        for item in arrow_items:
            item.update_label_display()

        # Each label is placed from its own arrow alone, so two of them can land
        # on top of each other. Separate them now that every one is in place.
        resolve_label_overlaps(arrow_items, diagram.boxes, diagram.arrows)
            
        # Draw Frame if enabled
        if self.frame_enabled and self.project_model:
            self.draw_frame()
        self.update()

    def set_frame_visible(self, visible):
        self.frame_enabled = visible
        if visible:
            if self.diagram_data and self.project_model:
                self.draw_frame()
        else:
            if self.frame_item:
                try:
                    if self.frame_item.scene() == self:
                        self.removeItem(self.frame_item)
                except RuntimeError:
                    pass
                self.frame_item = None

    def draw_frame(self):
        if not self.diagram_data or not self.project_model:
            return
            
        if self.frame_item:
            try:
                if self.frame_item.scene() == self:
                    self.removeItem(self.frame_item)
            except RuntimeError:
                pass
            self.frame_item = None
            
        # Determine Frame Size
        # Should encompass all items with some padding, or be a fixed page size?
        # Let's start with bounding rect of items + padding.
        items_rect = self.itemsBoundingRect()
        if items_rect.isNull():
             # Default size if empty
             rect = QRectF(0, 0, 1000, 700)
        else:
             # Add margin
             margin = 100
             rect = items_rect.adjusted(-margin, -margin-50, margin, margin+50)
             
             # Ensure minimum size (e.g., A4ish ratio or large enough for footer)
             if rect.width() < 600: rect.setWidth(600)
             if rect.height() < 400: rect.setHeight(400)
        
        self.frame_item = DiagramFrameItem(rect, self.project_model, self.diagram_data)
        self.addItem(self.frame_item)
        self.frame_item.setZValue(-100) # Send to back
        self.frame_item.create_text_items()

