import ezdxf
from ezdxf.math import Vec3, BoundingBox
from ezdxf import bbox as ezdxf_bbox

def cluster_and_pack_geometry(msp, in_x_min: float, in_y_min: float, in_x_max: float, in_y_max: float, stamp_w: float, stamp_h: float):
    # To fix overlapping geometry and large empty spaces, we should group entities into clusters.
    # Grouping logic: "друзья друзей" - intersecting or nearby bounding boxes.
    frame_layers = {'ГОСТ_Рамка', 'ГОСТ_Штамп_Линии', 'ГОСТ_Штамп_Текст', 'ГОСТ_Таблица_Текст', 'ИСП_Таблица', 'ИСП_Текст', 'ИС_Оформление_Штамп', 'ИС_Текст', 'ГОСТ_Контур_Толстый', 'ГОСТ_Контур_Тонкий', 'ГОСТ_Текст', 'Исполнительная_Оформление'}
    
    entities = []
    for ent in msp:
        layer = ent.dxf.layer if hasattr(ent.dxf, 'layer') else ''
        if layer not in frame_layers and not layer.startswith('ГОСТ_Рамка'):
            entities.append(ent)
            
    if not entities:
        return

    # Calculate bounding boxes
    boxes = []
    for ent in entities:
        try:
            b = ezdxf_bbox.extents([ent])
            if b.has_data:
                boxes.append((ent, b))
        except:
            pass

    if not boxes:
        return

    # Cluster boxes that overlap or are very close (e.g. distance < 5000 units in unscaled space)
    clusters = [] # list of lists of (ent, bbox)
    
    def boxes_intersect(b1, b2, threshold=1000.0):
        # Check if inflated boxes intersect
        if b1.extmax.x + threshold < b2.extmin.x or b2.extmax.x + threshold < b1.extmin.x:
            return False
        if b1.extmax.y + threshold < b2.extmin.y or b2.extmax.y + threshold < b1.extmin.y:
            return False
        return True

    for item in boxes:
        ent, b = item
        matched_clusters = []
        for i, cluster in enumerate(clusters):
            # Check against any item in cluster
            if any(boxes_intersect(b, cb) for _, cb in cluster):
                matched_clusters.append(i)
        
        if not matched_clusters:
            clusters.append([item])
        else:
            # Merge all matched clusters into the first one
            first_idx = matched_clusters[0]
            clusters[first_idx].append(item)
            for idx in sorted(matched_clusters[1:], reverse=True):
                clusters[first_idx].extend(clusters.pop(idx))

    # Now we have distinct clusters. Let's arrange them in a grid/row layout.
    # First, calculate cluster bounds
    cluster_boxes = []
    for cluster in clusters:
        cb = BoundingBox()
        for _, b in cluster:
            cb.extend([b.extmin, b.extmax])
        cluster_boxes.append(cb)

    # Sort clusters by x then y, or just area (largest first)
    # Let's pack them side by side
    margin = max((cb.extmax.x - cb.extmin.x) * 0.1 for cb in cluster_boxes) if cluster_boxes else 100.0
    
    current_x = 0.0
    for i, cluster in enumerate(clusters):
        cb = cluster_boxes[i]
        dx = current_x - cb.extmin.x
        dy = 0.0 - cb.extmin.y # align bottoms
        
        for ent, _ in cluster:
            ent.translate(dx, dy, 0)
            
        current_x += (cb.extmax.x - cb.extmin.x) + margin

    # After packing, calculate the NEW overall bounding box of the packed geometry
    packed_bbox = BoundingBox()
    for ent, _ in boxes: # The entities were translated in place
        try:
            b = ezdxf_bbox.extents([ent])
            if b.has_data:
                packed_bbox.extend([b.extmin, b.extmax])
        except:
            pass

    if not packed_bbox.has_data:
        return

    geom_w = packed_bbox.extmax.x - packed_bbox.extmin.x
    geom_h = packed_bbox.extmax.y - packed_bbox.extmin.y
    if geom_w < 0.1 or geom_h < 0.1:
        geom_w, geom_h = max(geom_w, 0.1), max(geom_h, 0.1)
        
    avail_w = (in_x_max - in_x_min) - stamp_w - 20.0
    avail_h = (in_y_max - in_y_min) - 20.0
    
    scale_w = avail_w / geom_w
    scale_h = avail_h / geom_h
    raw_scale = min(scale_w, scale_h) * 0.95
    
    # Optional: Snap to standard GOST scale (e.g. 1:100, 1:200, 1:500)
    # The true scale denominator is 1.0 / raw_scale.
    # We want a standard scale where denominator >= 1.0 / raw_scale
    M_req = 1.0 / raw_scale
    standard_M = [1, 2, 5, 10, 20, 25, 40, 50, 75, 100, 200, 250, 400, 500, 1000, 2000, 5000]
    chosen_M = M_req
    for M in standard_M:
        if M >= M_req:
            chosen_M = M
            break
            
    scale = 1.0 / chosen_M
    scale_str = f"1:{int(chosen_M)}" if chosen_M >= 1.0 else f"{round(chosen_M, 2)}"
    
    # Update stamp scale text if it exists
    for ent in msp.query('TEXT'):
        if hasattr(ent.dxf, 'text') and ent.dxf.text.startswith('Масштаб '):
            ent.dxf.text = f"Масштаб {scale_str}"
            
    cx_geom = (packed_bbox.extmin.x + packed_bbox.extmax.x) / 2.0
    cy_geom = (packed_bbox.extmin.y + packed_bbox.extmax.y) / 2.0
    
    cx_avail = in_x_min + avail_w / 2.0
    cy_avail = in_y_min + avail_h / 2.0
    
    for ent in entities:
        ent.scale(scale, scale, scale)
        ent.translate(cx_avail - cx_geom * scale, cy_avail - cy_geom * scale, 0)

