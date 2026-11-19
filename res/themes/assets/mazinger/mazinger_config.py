# Mazinger Robot Configuration - Multi-Design Support System
"""
Sistema de configuración para múltiples diseños de robot Mazinger.

Permite:
- Instalar varios robots como overlay decorativos
- Seleccionar el diseño activo desde GameHUD configurador
- Cambiar entre designs sin modificar archivos

Estructura de carpetas:
  library/hud_overlay/mazinger/
    - mazinger_anime_option1.png      (256x256, estilo clásico)
    - mazinger_vector_option3.png     (128x128, estilo minimalista)
    - mazinger_config.json            (configuración y selector activo)

Uso:
  GameHUD configurador -> HUD Overlay Settings -> Select Mazinger Design
"""

import json
import os

CONFIG_DIR = r"C:\Dev\Default Project\turing-smart-screen-python\assets"
OVERLAY_CONFIG_PATH = os.path.join(CONFIG_DIR, "mazinger", "mazinger_config.json")


# ============================================
# DISEÑOS DISPONIBLES (Lista de robots instalables)
# ============================================

AVAILABLE_DESIGNS = [
    {
        "id": "mazinger_anime_classic",
        "name": "Mazinger Z - Classic Anime Style",
        "filename": "mazinger_anime_option1.png",
        "size": "256x256",
        "style": "classic",
        "description": "Robot completo estilo anime Mazinger Z, pose dinámica, aura energética",
        "colors": {
            "blue": "#1E90FF",
            "gold": "#FFD700", 
            "red_visore": "#FF1E00",
            "energy": "#00CED1"
        },
        "best_for": ["anime fans", "retro gaming streamers", "elaborate decor"],
        "priority": 1  # Número menor = aparece primero en selector
    },
    {
        "id": "mazinger_vector_modern",
        "name": "Mazinger Z - Vector Clean Modern",
        "filename": "mazinger_vector_option3.png", 
        "size": "128x128",
        "style": "modern",
        "description": "Diseño minimalista flat design, escalable, UI limpia moderna",
        "colors": {
            "blue_electric": "#007FFF",
            "yellow_neon": "#FFCC00",
            "cyan_glow": "#66E0FF"
        },
        "best_for": ["modern gamers", "competitive esports", "minimalist UI"],
        "priority": 2
    }
]


# ============================================
# GENERAR CONFIGURACIÓN POR DEFECTO
# ============================================

def generate_default_config():
    """Genera archivo de configuración con todos los diseños disponibles."""
    
    # Asegurar que existe carpeta mazinger
    oz_dir = os.path.join(CONFIG_DIR, "mazinger")
    if not os.path.exists(oz_dir):
        os.makedirs(oz_dir)
        print(f"Created directory: {oz_dir}")
    
    # Configurar selector activo (por defecto usar anime classic)
    active_design_id = AVAILABLE_DESIGNS[0]["id"]  # Primero en lista
    
    config = {
        "version": "1.0",
        "author": "Sir-BLaDE - GameHUD v12",
        "active_design": active_design_id,
        "designs": AVAILABLE_DESIGNS,
        "settings": {
            "enable_overlay": True,
            "render_layer": "top",  # Renderiza encima del HUD existente
            "auto_scale": False,     # No escalar automáticamente (usa sprite fijo)
            "position_offset_x": 0,  # Posición X relativa al centro
            "position_offset_y": -100, # Desplazamiento Y (negativo = más arriba)
        }
    }
    
    # Guardar configuración
    config_path = OVERLAY_CONFIG_PATH
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print(f"[OK] Config saved to: {config_path}")
    print(f"[INFO] Active design: {active_design_id}")
    return config


# ============================================
# CARGAR CONFIGURACIÓN EXISTENTE
# ============================================

def load_config():
    """Carga configuración de diseños Mazinger existentes."""
    
    if not os.path.exists(OVERLAY_CONFIG_PATH):
        # No existe, generar por defecto
        return generate_default_config()
    
    with open(OVERLAY_CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    print(f"[OK] Loaded config from: {OVERLAY_CONFIG_PATH}")
    return config


# ============================================
# OBTENER DISEÑO ACTIVO
# ============================================

def get_active_design():
    """Obtiene información del diseño actualmente activo."""
    
    config = load_config()
    active_id = config["active_design"]
    active_design = next((d for d in AVAILABLE_DESIGNS if d["id"] == active_id), None)
    
    return {
        "config": config,
        "active_design": active_design,
        "filename": active_design["filename"],
        "path_to_file": os.path.join(CONFIG_DIR, "mazinger", active_design["filename"])
    }


# ============================================
# SELECCIONAR NUEVO DISEÑO ACTIVO
# ============================================

def set_active_design(designed_id):
    """Establece nuevo diseño como activo en configuración."""
    
    if not any(d["id"] == designed_id for d in AVAILABLE_DESIGNS):
        print(f"[ERROR] Design {designed_id} not found in available designs.")
        return False
    
    config = load_config()
    config["active_design"] = designed_id
    
    # Guardar nuevo estado
    config_path = OVERLAY_CONFIG_PATH
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print(f"[OK] Active design changed to: {designed_id}")
    return True


# ============================================
# LISTAR TODOS LOS DISEÑOS INSTALADOS
# ============================================

def list_installed_designs():
    """Devuelve lista de todos los diseños instalados para selector."""
    
    config = load_config()
    designs_for_selector = [d for d in config["designs"]]  # Todos disponibles
    
    # Ordenar por priority (menor primero)
    designs_for_selector.sort(key=lambda x: x.get("priority", 99))
    
    return {
        "config": config,
        "available_designs": designs_for_selector,
        "total_count": len(designs_for_selector)
    }


# ============================================
# GENERAR MENÚ DE SELECCIÓN PARA CONFIGURADOR HUD
# ============================================

def generate_configurator_menu():
    """Genera formato de menú para selector en configurador GameHUD."""
    
    available = list_installed_designs()["available_designs"]
    
    menu_items = []
    for design in available:
        status = "✓ ACTIVE" if design["id"] == config["active_design"] else ""
        
        menu_items.append({
            "label": f"{design['name']} {status}",
            "description": design["description"],
            "value": design["id"],
            "priority": design.get("priority", 99)
        })
    
    return {
        "menu_name": "Mazinger Robot Overlay Design",
        "category": "hud_overlay_settings",
        "items": menu_items,
        "default_value": config["active_design"]
    }


# ============================================
# MAIN - INICIALIZAR SISTEMA MAZINGER MULTI-DESIGN
# ============================================

if __name__ == "__main__":
    print("=" * 80)
    print("MAZINGER HUD ROBOT - MULTI-DESIGN SYSTEM")
    print("=" * 80)
    print()
    
    # Inicializar configurador por defecto
    config = generate_default_config()
    
    print("\n" + "=" * 80)
    print("INITIALIZED MAZINGER CONFIGURATION SYSTEM")
    print("=" * 80)
    print()
    print(f"Total designs installed: {len(AVAILABLE_DESIGNS)}")
    print(f"Current active design: {config['active_design']}")
    print()
    print("Available designs:")
    for idx, design in enumerate(AVAILABLE_DESIGNS, 1):
        status = " [ACTIVE]" if design["id"] == config["active_design"] else ""
        print(f"  {idx}. {design['name']}{status}")
        print(f"     File: {design['filename']}")
        print(f"     Size: {design['size']}")
        print()
    
    # Generar menú para configurador
    menu = generate_configurator_menu()
    print("=" * 80)
    print("CONFIGURATOR MENU FORMAT:")
    print("=" * 80)
    for item in menu["items"]:
        print(f"  [{item['priority']}] {item['label']}")
        print(f"      Description: {item['description']}")
    
    print()
    print("USE THIS IN YOUR GameHUD CONFIGURATOR:")
    print("- Add setting with name: 'mazinger_design_id'")
    print("- Type: Dropdown/Select box")
    print("- Default value: menu['default_value']")
    print("- Options: All items in menu['items'] (by 'value' field)")
    
    # Guardar menú como referencia
    with open(os.path.join(CONFIG_DIR, "mazinger", "CONFIGURATOR_MENU.txt"), 'w') as f:
        f.write("Mazinger Configurator Menu - GameHUD Settings\n")
        for item in menu["items"]:
            f.write(f"  [{item['priority']}] {item['label']} (value={item['value']})\n")
    
    print()
    print("Menu saved to: CONFIGURATOR_MENU.txt")
