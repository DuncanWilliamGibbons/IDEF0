"""Source-code exports of an IDEF0 functional architecture.

One method per activity, wired the way the model says the signals flow. Every
generated file is meant to compile and run as it stands: the previous exports
emitted two `activity_A0` methods (A-0 and A0 both flattened to the same name),
read variables in box-id order rather than in the order the model produces them,
and passed mechanisms under one name while declaring them under another.

The wiring goes through a per-activity context dictionary rather than plain
locals. IDEF0 models contain feedback loops, so no ordering of the calls can put
every write before every read; a context makes the unresolved-yet case a missing
key at runtime instead of code that will not compile.
"""
from typing import Dict, List

from src.core.export_common import (
    Activity, build_activity_tree, camel, model_title, sanitize, snake,
    unique, wiring,
)
from src.core.model import IDEF0Model


def _wrap_doc(text: str, width: int = 72) -> List[str]:
    words = (text or "").split()
    lines, current = [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def _assign_names(roots: List[Activity], style) -> None:
    """Give every activity and every signal a unique identifier in `style`."""
    used_methods = set()
    signal_names: Dict[str, str] = {}
    for root in roots:
        for activity in root.walk():
            base = style(f"{activity.node_id}_{activity.title}")
            activity.name = unique(base, used_methods)
            for flow in activity.all_flows():
                if flow.key not in signal_names:
                    signal_names[flow.key] = style(flow.display or flow.code or flow.key)
                flow.name = signal_names[flow.key]


def _icom_doc(activity: Activity) -> List[str]:
    rows = []
    for title, flows in (("Inputs", activity.inputs),
                         ("Controls", activity.controls),
                         ("Outputs", activity.outputs),
                         ("Mechanisms", activity.mechanisms)):
        if flows:
            rows.append(f"{title + ':':<12}" + ", ".join(f.qualified for f in flows))
    return rows


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------
def export_to_python(model: IDEF0Model) -> str:
    roots = build_activity_tree(model)
    _assign_names(roots, snake)
    name = model_title(model)

    out: List[str] = [
        '"""Functional architecture generated from an IDEF0 model.',
        '',
        f'Model:     {name}',
        f'Purpose:   {getattr(model, "purpose", "") or "-"}',
        f'Viewpoint: {getattr(model, "viewpoint", "") or "-"}',
        '',
        'Every activity takes its ICOMs as keyword arguments and returns a dict',
        'of the signals it produces. Replace perform_leaf_task, or override the',
        'leaf methods, to give the architecture behaviour.',
        '"""',
        'import logging',
        '',
        'logger = logging.getLogger("idef0")',
        '',
        '',
        'class IDEF0Architecture:',
        f'    """{name}"""',
        '',
    ]

    activities = [a for root in roots for a in root.walk()]
    if not activities:
        out.append('    pass')
        return "\n".join(out) + "\n"

    for activity in activities:
        params = activity.parameters
        signature = ", ".join(["self"] + [f"{f.name}=None" for f in params])
        out.append(f'    def {activity.name}({signature}):')
        out.append(f'        """{activity.title}')
        out.append('')
        out.append(f'        Node: {activity.node_id}')
        for row in _icom_doc(activity):
            out.append(f'        {row}')
        for line in _wrap_doc(activity.description):
            out.append(f'        {line}')
        out.append('        """')

        out.append('        context = {')
        for flow in params:
            out.append(f'            "{flow.name}": {flow.name},')
        out.append('        }')

        if activity.is_decomposed:
            produced = wiring(activity)
            for child in activity.children:
                source = ", ".join(
                    f'{f.name}=context.get("{f.name}")' for f in child.parameters)
                out.append(f'        # {child.node_id} {child.title}')
                if source:
                    out.append(f'        context.update(self.{child.name}({source}))')
                else:
                    out.append(f'        context.update(self.{child.name}())')
            unresolved = [f for f in activity.outputs if f.key not in produced]
            if unresolved:
                out.append('        # produced outside this decomposition')
                for flow in unresolved:
                    out.append(f'        context.setdefault("{flow.name}", None)')
        else:
            names = ", ".join(f'"{f.name}"' for f in activity.outputs)
            out.append('        context.update(self.perform_leaf_task(')
            out.append(f'            "{activity.node_id}", "{activity.title}",')
            out.append(f'            ({names + "," if names else ""}), context))')

        out.append('        return {')
        for flow in activity.outputs:
            out.append(f'            "{flow.name}": context.get("{flow.name}"),')
        out.append('        }')
        out.append('')

    out.append('    def perform_leaf_task(self, node, title, outputs, context):')
    out.append('        """Stand-in for a leaf activity. Override to give it behaviour."""')
    out.append('        logger.info("%s %s", node, title)')
    out.append('        return {name: f"{node}.{name}" for name in outputs}')
    out.append('')

    root_names = [r.name for r in roots]
    out.append('')
    out.append('if __name__ == "__main__":')
    out.append('    logging.basicConfig(level=logging.INFO)')
    out.append('    architecture = IDEF0Architecture()')
    for root_name in root_names:
        out.append(f'    print(architecture.{root_name}())')
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------
def export_to_java(model: IDEF0Model, class_name: str = "IDEF0Architecture") -> str:
    roots = build_activity_tree(model)
    _assign_names(roots, camel)
    name = model_title(model)
    cls = sanitize(class_name)

    out: List[str] = [
        '/**',
        ' * Functional architecture generated from an IDEF0 model.',
        ' *',
        f' * Model:     {name}',
        f' * Purpose:   {getattr(model, "purpose", "") or "-"}',
        f' * Viewpoint: {getattr(model, "viewpoint", "") or "-"}',
        ' *',
        ' * Every activity takes its ICOMs as arguments and returns a map of the',
        ' * signals it produces. Override the leaf methods to give it behaviour.',
        ' */',
        'import java.util.HashMap;',
        'import java.util.LinkedHashMap;',
        'import java.util.Map;',
        'import java.util.logging.Logger;',
        '',
        f'public class {cls} {{',
        '',
        f'    private static final Logger LOGGER = Logger.getLogger({cls}.class.getName());',
        '',
    ]

    activities = [a for root in roots for a in root.walk()]

    for activity in activities:
        params = activity.parameters
        signature = ", ".join(f"Object {f.name}" for f in params)
        out.append('    /**')
        out.append(f'     * {activity.title}')
        out.append(f'     * <p>Node: {activity.node_id}')
        for row in _icom_doc(activity):
            out.append(f'     * <br>{row}')
        out.append('     */')
        out.append(f'    public Map<String, Object> {activity.name}({signature}) {{')
        out.append('        Map<String, Object> context = new LinkedHashMap<>();')
        for flow in params:
            out.append(f'        context.put("{flow.name}", {flow.name});')

        if activity.is_decomposed:
            for child in activity.children:
                args = ", ".join(f'context.get("{f.name}")' for f in child.parameters)
                out.append(f'        // {child.node_id} {child.title}')
                out.append(f'        context.putAll({child.name}({args}));')
        else:
            names = ", ".join(f'"{f.name}"' for f in activity.outputs)
            out.append(f'        context.putAll(performLeafTask("{activity.node_id}", '
                       f'"{activity.title}", context{", " + names if names else ""}));')

        out.append('        Map<String, Object> results = new LinkedHashMap<>();')
        for flow in activity.outputs:
            out.append(f'        results.put("{flow.name}", context.get("{flow.name}"));')
        out.append('        return results;')
        out.append('    }')
        out.append('')

    out.append('    protected Map<String, Object> performLeafTask(String node, String title,')
    out.append('                                                 Map<String, Object> context,')
    out.append('                                                 String... outputs) {')
    out.append('        LOGGER.info(node + " " + title);')
    out.append('        Map<String, Object> results = new HashMap<>();')
    out.append('        for (String output : outputs) {')
    out.append('            results.put(output, node + "." + output);')
    out.append('        }')
    out.append('        return results;')
    out.append('    }')
    out.append('')
    out.append('    public static void main(String[] args) {')
    out.append(f'        {cls} architecture = new {cls}();')
    for root in roots:
        nulls = ", ".join("null" for _ in root.parameters)
        out.append(f'        System.out.println(architecture.{root.name}({nulls}));')
    out.append('    }')
    out.append('}')
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# C++
# ---------------------------------------------------------------------------
def export_to_cpp(model: IDEF0Model, class_name: str = "IDEF0Architecture") -> str:
    roots = build_activity_tree(model)
    _assign_names(roots, snake)
    name = model_title(model)
    cls = sanitize(class_name)

    out: List[str] = [
        '// Functional architecture generated from an IDEF0 model.',
        '//',
        f'// Model:     {name}',
        f'// Purpose:   {getattr(model, "purpose", "") or "-"}',
        f'// Viewpoint: {getattr(model, "viewpoint", "") or "-"}',
        '//',
        '// Every activity takes its ICOMs as arguments and returns the signals it',
        '// produces. Override the leaf methods to give the architecture behaviour.',
        '',
        '#include <initializer_list>',
        '#include <iostream>',
        '#include <map>',
        '#include <string>',
        '',
        'namespace idef0 {',
        '',
        'using Value = std::string;',
        'using Context = std::map<std::string, Value>;',
        '',
        'inline Value lookup(const Context& context, const std::string& key) {',
        '    const auto found = context.find(key);',
        '    return found == context.end() ? Value() : found->second;',
        '}',
        '',
        'inline void merge(Context& into, const Context& from) {',
        '    for (const auto& entry : from) {',
        '        into[entry.first] = entry.second;',
        '    }',
        '}',
        '',
        f'class {cls} {{',
        ' public:',
        f'    virtual ~{cls}() = default;',
        '',
    ]

    activities = [a for root in roots for a in root.walk()]

    for activity in activities:
        params = activity.parameters
        signature = ", ".join(f"Value {f.name}" for f in params)
        out.append(f'    // {activity.title}  (node {activity.node_id})')
        for row in _icom_doc(activity):
            out.append(f'    // {row}')
        out.append(f'    virtual Context {activity.name}({signature}) {{')
        out.append('        Context context;')
        for flow in params:
            out.append(f'        context["{flow.name}"] = {flow.name};')

        if activity.is_decomposed:
            for child in activity.children:
                args = ", ".join(f'lookup(context, "{f.name}")'
                                 for f in child.parameters)
                out.append(f'        // {child.node_id} {child.title}')
                out.append(f'        merge(context, {child.name}({args}));')
        else:
            names = ", ".join(f'"{f.name}"' for f in activity.outputs)
            out.append(f'        merge(context, perform_leaf_task("{activity.node_id}", '
                       f'"{activity.title}", {{{names}}}));')

        out.append('        Context results;')
        for flow in activity.outputs:
            out.append(f'        results["{flow.name}"] = lookup(context, "{flow.name}");')
        out.append('        return results;')
        out.append('    }')
        out.append('')

    out.append('    virtual Context perform_leaf_task(const std::string& node,')
    out.append('                                      const std::string& title,')
    out.append('                                      std::initializer_list<const char*> outputs) {')
    out.append('        std::cout << node << " " << title << std::endl;')
    out.append('        Context results;')
    out.append('        for (const char* output : outputs) {')
    out.append('            results[output] = node + "." + output;')
    out.append('        }')
    out.append('        return results;')
    out.append('    }')
    out.append('};')
    out.append('')
    out.append('}  // namespace idef0')
    out.append('')
    out.append('int main() {')
    out.append(f'    idef0::{cls} architecture;')
    for root in roots:
        empties = ", ".join('idef0::Value()' for _ in root.parameters)
        out.append(f'    for (const auto& entry : architecture.{root.name}({empties})) {{')
        out.append('        std::cout << entry.first << " = " << entry.second << std::endl;')
        out.append('    }')
    out.append('    return 0;')
    out.append('}')
    return "\n".join(out) + "\n"
