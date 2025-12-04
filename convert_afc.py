from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM

svg_path = 'raw_team_logos/AFC.svg'
png_path = 'team_logos/afc.png'

drawing = svg2rlg(svg_path)
renderPM.drawToFile(drawing, png_path, fmt='PNG', dpi=150)
print(f'Successfully converted Adelaide logo to {png_path}')
