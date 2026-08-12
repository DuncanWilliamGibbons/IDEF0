import xml.etree.ElementTree as ET
from xml.dom import minidom
from src import APP_NAME, __version__
from src.core.model import IDEF0Model, Diagram, ActivityBox, Arrow, ArrowType, Point

def model_to_xml(model: IDEF0Model, functional_only: bool = False) -> str:
    root = ET.Element("IDEF0Model")
    root.set("name", model.name)
    # Which build wrote the file, so a model opened years from now says what
    # produced it. Distinct from <Version>, which is the modeller's own version
    # number for the model itself.
    root.set("generator", APP_NAME)
    root.set("generatorVersion", __version__)

    # Context info
    if model.purpose:
        p_elem = ET.SubElement(root, "Purpose")
        p_elem.text = model.purpose
    if model.viewpoint:
        v_elem = ET.SubElement(root, "Viewpoint")
        v_elem.text = model.viewpoint
        
    # Frame Info
    if model.author:
        ET.SubElement(root, "Author").text = model.author
    if model.date_created:
        ET.SubElement(root, "Date").text = model.date_created
    if model.version:
        ET.SubElement(root, "Version").text = model.version
    
    for diag in model.diagrams:
        diag_elem = ET.SubElement(root, "Diagram")
        diag_elem.set("node_number", diag.node_number)
        diag_elem.set("title", diag.title)
        if diag.parent_diagram_id:
            diag_elem.set("parent_diagram_id", diag.parent_diagram_id)
        if getattr(diag, "c_number", ""):
            diag_elem.set("c_number", diag.c_number)
            
        for box in diag.boxes:
            box_elem = ET.SubElement(diag_elem, "Box")
            box_elem.set("id", box.id)
            box_elem.set("name", box.name)
            box_elem.set("description", box.description)
            
            if not functional_only:
                box_elem.set("x", str(box.x))
                box_elem.set("y", str(box.y))
                box_elem.set("width", str(box.width))
                box_elem.set("height", str(box.height))
                # Add fonts
                box_elem.set("font_family", box.font_family)
                box_elem.set("font_size", str(box.font_size))
                box_elem.set("font_bold", str(box.font_bold).lower())
                box_elem.set("font_italic", str(box.font_italic).lower())
                box_elem.set("color", box.color)
            
        for arrow in diag.arrows:
            arrow_elem = ET.SubElement(diag_elem, "Arrow")
            arrow_elem.set("id", arrow.id)
            if arrow.source_box_id: arrow_elem.set("source_box_id", arrow.source_box_id)
            if arrow.target_box_id: arrow_elem.set("target_box_id", arrow.target_box_id)
            arrow_elem.set("type", arrow.type.value)
            arrow_elem.set("label", arrow.label)
            arrow_elem.set("description", arrow.description)
            if arrow.branch_parent_id: arrow_elem.set("branch_parent_id", arrow.branch_parent_id)
            if arrow.join_target_id: arrow_elem.set("join_target_id", arrow.join_target_id)
            if arrow.is_manual_connection: arrow_elem.set("is_manual_connection", str(arrow.is_manual_connection).lower())
            arrow_elem.set("tunnel_source", str(arrow.tunnel_source).lower())
            arrow_elem.set("tunnel_target", str(arrow.tunnel_target).lower())
            if arrow.icom_code: arrow_elem.set("icom_code", arrow.icom_code)
            if arrow.auto_icom_code: arrow_elem.set("auto_icom_code", arrow.auto_icom_code)
            if arrow.auto_icom_code_manual: arrow_elem.set("auto_icom_code_manual", "true")
            
            if not functional_only:
                # Styling
                arrow_elem.set("color", arrow.color)
                arrow_elem.set("thickness", str(arrow.thickness))
                arrow_elem.set("style", arrow.style)
                arrow_elem.set("arrowhead_style", arrow.arrowhead_style)
                arrow_elem.set("icom_callout_style", arrow.icom_callout_style)
                arrow_elem.set("hide_label", str(arrow.hide_label).lower())
                arrow_elem.set("label_offset_x", str(arrow.label_offset_x))
                arrow_elem.set("label_offset_y", str(arrow.label_offset_y))
                
                # Add label fonts
                arrow_elem.set("label_font_family", arrow.label_font_family)
                arrow_elem.set("label_font_size", str(arrow.label_font_size))
                arrow_elem.set("label_font_bold", str(arrow.label_font_bold).lower())
                arrow_elem.set("label_font_italic", str(arrow.label_font_italic).lower())
                
                if arrow.segments:
                    seg_elem = ET.SubElement(arrow_elem, "Segments")
                    for p in arrow.segments:
                        p_elem = ET.SubElement(seg_elem, "Point")
                        p_elem.set("x", str(p.x))
                        p_elem.set("y", str(p.y))
                
                if arrow.junction_point:
                    jp_elem = ET.SubElement(arrow_elem, "JunctionPoint")
                    jp_elem.set("x", str(arrow.junction_point.x))
                    jp_elem.set("y", str(arrow.junction_point.y))
                    
                if arrow.branch_points:
                    bp_elem = ET.SubElement(arrow_elem, "BranchPoints")
                    for p in arrow.branch_points:
                        p_elem = ET.SubElement(bp_elem, "Point")
                        p_elem.set("x", str(p.x))
                        p_elem.set("y", str(p.y))
                        
                if arrow.join_points:
                    jp_elem = ET.SubElement(arrow_elem, "JoinPoints")
                    for p in arrow.join_points:
                        p_elem = ET.SubElement(jp_elem, "Point")
                        p_elem.set("x", str(p.x))
                        p_elem.set("y", str(p.y))

    # Pretty print
    xml_str = ET.tostring(root, encoding='utf-8')
    parsed = minidom.parseString(xml_str)
    return parsed.toprettyxml(indent="    ")

def xml_to_model(xml_str: str) -> IDEF0Model:
    root = ET.fromstring(xml_str)
    model = IDEF0Model(root.get("name"))
    
    # Read Context Info
    p_elem = root.find("Purpose")
    if p_elem is not None and p_elem.text:
        model.purpose = p_elem.text
    v_elem = root.find("Viewpoint")
    if v_elem is not None and v_elem.text:
        model.viewpoint = v_elem.text
        
    # Read Frame Info
    a_elem = root.find("Author")
    if a_elem is not None and a_elem.text: model.author = a_elem.text
    
    d_elem = root.find("Date")
    if d_elem is not None and d_elem.text: model.date_created = d_elem.text
    
    vers_elem = root.find("Version")
    if vers_elem is not None and vers_elem.text: model.version = vers_elem.text
    
    # IDEF0Model.__init__ adds A-0 automatically, clear it before loading
    model.diagrams = []
    
    for diag_elem in root.findall("Diagram"):
        diag = Diagram(
            node_number=diag_elem.get("node_number"),
            title=diag_elem.get("title"),
            parent_diagram_id=diag_elem.get("parent_diagram_id"),
            c_number=diag_elem.get("c_number", "")
        )
        
        for box_elem in diag_elem.findall("Box"):
            box = ActivityBox(
                id=box_elem.get("id"),
                name=box_elem.get("name"),
                description=box_elem.get("description", ""),
                x=float(box_elem.get("x", 0)),
                y=float(box_elem.get("y", 0)),
                width=float(box_elem.get("width", 150)),
                height=float(box_elem.get("height", 100)),
                font_family=box_elem.get("font_family", "Arial"),
                font_size=int(box_elem.get("font_size", 10)),
                font_bold=box_elem.get("font_bold", "false") == "true",
                font_italic=box_elem.get("font_italic", "false") == "true",
                color=box_elem.get("color", "#ffffff")
            )
            diag.boxes.append(box)
            
        for arrow_elem in diag_elem.findall("Arrow"):
            arrow = Arrow(
                id=arrow_elem.get("id"),
                source_box_id=arrow_elem.get("source_box_id"),
                target_box_id=arrow_elem.get("target_box_id"),
                type=ArrowType(arrow_elem.get("type")),
                label=arrow_elem.get("label", ""),
                description=arrow_elem.get("description", ""),
                branch_parent_id=arrow_elem.get("branch_parent_id"),
                join_target_id=arrow_elem.get("join_target_id"),
                is_manual_connection=arrow_elem.get("is_manual_connection") == "true",
                tunnel_source=arrow_elem.get("tunnel_source") == "true",
                tunnel_target=arrow_elem.get("tunnel_target") == "true",
                color=arrow_elem.get("color", "#000000"),
                thickness=int(arrow_elem.get("thickness", "1")),
                style=arrow_elem.get("style", "Solid"),
                arrowhead_style=arrow_elem.get("arrowhead_style", "Standard"),
                label_offset_x=float(arrow_elem.get("label_offset_x", "0.0")),
                label_offset_y=float(arrow_elem.get("label_offset_y", "0.0")),
                label_font_family=arrow_elem.get("label_font_family", "Arial"),
                label_font_size=int(arrow_elem.get("label_font_size", 9)),
                label_font_bold=arrow_elem.get("label_font_bold", "false") == "true",
                label_font_italic=arrow_elem.get("label_font_italic", "false") == "true",
                icom_code=arrow_elem.get("icom_code"),
                auto_icom_code=arrow_elem.get("auto_icom_code"),
                auto_icom_code_manual=arrow_elem.get("auto_icom_code_manual") == "true",
                icom_callout_style=arrow_elem.get("icom_callout_style", "Jagged"),
                hide_label=arrow_elem.get("hide_label", "false") == "true"
            )
            
            seg_elem = arrow_elem.find("Segments")
            if seg_elem is not None:
                for p_elem in seg_elem.findall("Point"):
                    arrow.segments.append(Point(float(p_elem.get("x")), float(p_elem.get("y"))))
                    
            jp_elem = arrow_elem.find("JunctionPoint")
            if jp_elem is not None:
                arrow.junction_point = Point(float(jp_elem.get("x")), float(jp_elem.get("y")))
                
            bp_elem = arrow_elem.find("BranchPoints")
            if bp_elem is not None:
                for p_elem in bp_elem.findall("Point"):
                    arrow.branch_points.append(Point(float(p_elem.get("x")), float(p_elem.get("y"))))
                    
            jp_list_elem = arrow_elem.find("JoinPoints")
            if jp_list_elem is not None:
                for p_elem in jp_list_elem.findall("Point"):
                    arrow.join_points.append(Point(float(p_elem.get("x")), float(p_elem.get("y"))))
                    
            diag.arrows.append(arrow)
            
        model.add_diagram(diag)
        
    return model
