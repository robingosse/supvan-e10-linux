"""Centralized visual design system for SUPVAN Label Studio.

Keep the palette and reusable control styling here so future workstation themes
or product variants do not require hunting through UI construction code.
"""

PALETTE = {
    "ink": "#20354A",
    "ink_soft": "#49657D",
    "navy": "#244D6E",
    "navy_deep": "#193A55",
    "blue": "#5F88AD",
    "blue_hover": "#7299BB",
    "blue_pressed": "#466F94",
    "panel": "#D7E5F2",
    "panel_alt": "#C5D9EA",
    "canvas": "#AFC7DC",
    "cream": "#FFF4D9",
    "cream_soft": "#FAEBCB",
    "paper": "#FFF9E9",
    "line": "#93AFC6",
    "danger": "#936C76",
    "danger_border": "#77535D",
    "white": "#FFF9EC",
}

THEME_CSS = f"""
window,
dialog,
messagedialog {{
    background-color: {PALETTE['panel_alt']};
    color: {PALETTE['ink']};
}}

headerbar {{
    background-image: none;
    background-color: {PALETTE['navy']};
    color: {PALETTE['white']};
    border-bottom: 1px solid {PALETTE['navy_deep']};
    box-shadow: 0 3px 8px alpha({PALETTE['navy_deep']}, 0.38);
    padding: 8px;
}}

headerbar label,
headerbar .title,
headerbar .subtitle {{ color: {PALETTE['white']}; }}

.studio-panel {{
    background-color: {PALETTE['panel']};
    color: {PALETTE['ink']};
    padding: 13px;
    box-shadow: inset 0 1px alpha(#ffffff, 0.45);
}}

.section-title {{
    color: {PALETTE['navy']};
    font-weight: 700;
    margin-top: 10px;
    margin-bottom: 3px;
}}

.muted {{ color: {PALETTE['ink_soft']}; }}

button.studio-button,
headerbar button,
combobox button,
spinbutton button {{
    background-image: none;
    background-color: {PALETTE['blue']};
    color: {PALETTE['white']};
    border: 1px solid #456D90;
    border-radius: 13px;
    box-shadow: inset 0 1px alpha(#ffffff, 0.34), 0 3px 6px alpha({PALETTE['navy_deep']}, 0.28);
    padding: 7px 13px;
    min-height: 23px;
}}

button.studio-button label,
headerbar button label,
combobox button label,
spinbutton button {{ color: {PALETTE['white']}; }}

button.studio-button:hover,
headerbar button:hover,
combobox button:hover,
spinbutton button:hover {{
    background-color: {PALETTE['blue_hover']};
    border-color: #527A9E;
    box-shadow: inset 0 1px alpha(#ffffff, 0.40), 0 4px 8px alpha({PALETTE['navy_deep']}, 0.30);
}}

button.studio-button:active,
headerbar button:active,
combobox button:active,
spinbutton button:active {{
    background-color: {PALETTE['blue_pressed']};
    box-shadow: inset 0 2px 4px alpha({PALETTE['navy_deep']}, 0.34);
}}

button.studio-button:disabled,
headerbar button:disabled {{
    background-color: #A6B8C8;
    color: #E8EEF3;
    border-color: #8FA4B6;
    box-shadow: none;
}}

button.print-button {{
    background-color: #376F9C;
    border-color: #285A80;
    color: {PALETTE['white']};
    font-weight: 700;
    padding-left: 17px;
    padding-right: 17px;
}}
button.print-button:hover {{ background-color: #4A82AF; }}

button.workbench-button {{
    background-color: #315C80;
    border-color: #234662;
    font-weight: 700;
}}
button.workbench-button:hover {{ background-color: #46779D; }}

button.danger-button {{
    background-color: {PALETTE['danger']};
    border-color: {PALETTE['danger_border']};
    color: {PALETTE['white']};
}}

entry,
spinbutton entry,
combobox entry,
textview,
textview text {{
    background-color: {PALETTE['cream']};
    color: {PALETTE['ink']};
    border: 1px solid {PALETTE['line']};
    border-radius: 9px;
    box-shadow: inset 0 1px 2px alpha({PALETTE['navy_deep']}, 0.12);
}}

entry:focus,
spinbutton entry:focus,
combobox entry:focus,
textview:focus {{
    border-color: #5A85AA;
    box-shadow: 0 0 0 1px alpha(#5A85AA, 0.35), inset 0 1px 2px alpha({PALETTE['navy_deep']}, 0.10);
}}

entry selection,
textview text selection {{
    background-color: {PALETTE['blue_hover']};
    color: #ffffff;
}}

entry,
spinbutton,
combobox {{ min-height: 32px; }}

checkbutton {{ color: {PALETTE['ink']}; }}
checkbutton check {{
    background-color: {PALETTE['cream']};
    border: 1px solid {PALETTE['line']};
    border-radius: 5px;
    box-shadow: inset 0 1px 2px alpha({PALETTE['navy_deep']}, 0.12);
}}
checkbutton check:checked {{ background-color: {PALETTE['blue']}; }}

list,
listbox,
listbox row {{
    background-color: #EAF2F8;
    color: {PALETTE['ink']};
}}
listbox {{
    border-radius: 10px;
    box-shadow: inset 0 1px 3px alpha({PALETTE['navy_deep']}, 0.13);
}}
listbox row {{ border-bottom: 1px solid #CBD9E5; }}
listbox row:selected {{
    background-color: #6F94B5;
    color: {PALETTE['white']};
}}
listbox row:selected label {{ color: {PALETTE['white']}; }}

.canvas-frame {{ background-color: {PALETTE['canvas']}; }}
.status-bar {{
    background-color: #D6E4EF;
    color: #314B62;
    box-shadow: inset 0 1px alpha(#ffffff, 0.45);
}}

separator {{ background-color: #93AEC4; }}
scrollbar trough {{ background-color: #BFD2E1; }}
scrollbar slider {{
    background-color: #7799B6;
    border-radius: 9px;
    min-width: 10px;
    min-height: 10px;
}}
scrollbar slider:hover {{ background-color: #678BAA; }}
"""
