import re

with open('/app/algo_packer.py', 'r') as f:
    content = f.read()

# Instead of just an arbitrary scale factor, snap to a GOST scale
# scale is `min(scale_w, scale_h) * 0.95`.
# The real scale denominator `M` (where scale is 1:M) is 1 / scale.
# Let's find the nearest standard M, ensuring M >= 1 / scale so it fits.
# Or just use the raw scale but update the stamp text.

def replace_scale(m):
    return """    scale_w = avail_w / geom_w
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
            
    cx_geom = (packed_bbox.extmin.x + packed_bbox.extmax.x) / 2.0"""

content = re.sub(
    r'    scale_w = avail_w / geom_w\n    scale_h = avail_h / geom_h\n    scale = min\(scale_w, scale_h\) \* 0\.95\n    \n    cx_geom = \(packed_bbox\.extmin\.x \+ packed_bbox\.extmax\.x\) / 2\.0',
    replace_scale(None),
    content
)

with open('/app/algo_packer.py', 'w') as f:
    f.write(content)

