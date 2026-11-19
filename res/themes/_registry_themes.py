#!/usr/bin/env python3
"""
GameHUD Theme Registry - Central tema manager para todos los temas.
Este file registra todos los temas disponibles para el configurador de Turing System Monitor.

Copiar este file a: res/themes/_registry_themes.py (o registrar en configurador)
"""

import os
import json

THEMES_ROOT = r"C:\Users\Gowayn\AppData\Local\Programs\Turing System Monitor\turing-smart-screen-python\res\themes"


def get_all_available_themes():
    """
    Escanea todas las subcarpetas de themes para encontrar temas disponibles.
    
    Retorna un dict con:
      - id del tema
      - display_name visible en configurador
      - path donde está instalado
      - enabled_by_default (si es tema por defecto)
    """
    
    themes = {}
    
    # Carpeta base GameHUD
    gamehud_path = os.path.join(THEMES_ROOT, "GameHUD")
    
    if not os.path.exists(gamehud_path):
        return themes
    
    # 1. Tema base GameHUD (siempre disponible)
    themes["gamehud"] = {
        "id": "gamehud",
        "display_name": "GameHUD",
        "category": "statistical",
        "enabled_by_default": False,
        "path": gamehud_path,
        "description": "Estadísticas del sistema con skin minimalista"
    }
    
    # 2. Tema Mazinger Z (si existe el theme manager)
    mazinger_manager = os.path.join(gamehud_path, "mazinger_default_theme.py")
    
    if os.path.exists(mazinger_manager):
        config_file = os.path.join(gamehud_path, "assets", "mazinger", "mazinger_config.json")
        
        # Leer info del tema Mazinger de su config
        theme_info = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    theme_id = config.get('theme_id', 'mazinger_z_anime')
                    display_name = config.get('name', 'Mazinger Z Anime Classic')
                    
                    theme_info[theme_id] = {
                        "id": theme_id,
                        "display_name": display_name if '🤖' in display_name else f"🤖 {display_name}",
                        "category": "robot_overlay",
                        "enabled_by_default": config.get('default_enabled', True),
                        "path": gamehud_path,
                        "description": config.get('description', 'Robot anime overlay sobre estadísticas')
                    }
            except Exception as e:
                print(f"[Registry] Error leyendo Mazinger config: {e}")
        
        # Añadir Mazinger (o placeholder si no tiene config)
        if not theme_info and os.path.exists(gamehud_path):
            theme_info["mazinger_z_anime"] = {
                "id": "mazinger_z_anime",
                "display_name": "🤖 Mazinger Z Anime Classic",
                "category": "robot_overlay",
                "enabled_by_default": True,
                "path": gamehud_path,
                "description": "Robot anime overlay sobre estadísticas"
            }
        
        themes.update(theme_info)
    
    return themes


def list_themes_for_selector():
    """
    Prepara lista formateada para selector dropdown del configurador.
    
    Retorno: List[str] con strings tipo: "ID - Display Name [ACTIVO]"
    """
    
    all_themes = get_all_available_themes()
    
    result = []
    for theme_id, info in sorted(all_themes.items()):
        is_active = (info.get('enabled_by_default') or False and 
                     theme_id == 'mazinger_z_anime')
        
        status = "" if not is_active else " ✅ [ACTIVO]"
        
        # Limpiar emojis para comparar IDs
        display_name = info['display_name']
        
        result.append(f"{theme_id} - {display_name}{status}")
    
    return result


def register_theme_in_configurator(themes_file=None):
    """
    Registra este tema Mazinger Z en el sistema de selección de temas.
    
    Args:
        themes_file: Path opcional a archivo de registro (por defecto usa carpeta registry/)
        
    Retorno: True si registro exitoso, False si error o ya registrado.
    """
    
    print("\n=== REGISTRANDO TEMA MAZINGER Z EN CONFIGURADOR DE TURING ===\n")
    
    # Obtener todos los temas disponibles
    themes = get_all_available_themes()
    
    if not themes:
        print("❌ No se encontraron temas registrados")
        return False
    
    # Mostrar resumen de temas encontrados
    print(f"📦 Temas encontrados ({len(themes)}):")
    for theme_id, info in sorted(themes.items()):
        active_marker = " ✅ DEFAULT" if info.get('enabled_by_default') else ""
        print(f"\n  {theme_id.upper()}")
        print(f"    Nombre: {info['display_name']}{active_marker}")
        print(f"    Categoría: {info['category']}")
        print(f"    Descripción: {info['description']}")
    
    # Guardar registro en archivo si existe carpeta registry/
    registry_dir = os.path.join(THEMES_ROOT, "registry")
    if not os.path.exists(registry_dir):
        os.makedirs(registry_dir)
    
    # Crear archivo de registro centralizado
    registry_file = os.path.join(registry_dir, "registered_themes.json")
    
    try:
        with open(registry_file, 'w', encoding='utf-8') as f:
            json.dump({
                "_meta": {
                    "name": "GameHUD Theme Registry",
                    "version": "1.0",
                    "description": "Registro central de temas para configurador de Turing System Monitor"
                },
                "themes": list(themes.values())
            }, f, indent=2)
        
        print(f"\n✅ Tema registrado en: {registry_file}")
        print("   El configurador puede leer este archivo para mostrar todos los temas")
        
    except Exception as e:
        print(f"\n⚠️  No se pudo guardar registro: {e}")
    
    return True


if __name__ == "__main__":
    # Modo por defecto: mostrar todos los temas disponibles
    print("=== GAMEHUD THEME REGISTRY ===\n")
    
    themes = get_all_available_themes()
    
    if not themes:
        print("❌ No se encontraron temas disponibles.")
        print("\nPara instalar nuevos temas:")
        print("  1. Copia mazinger_default_theme.py a GameHUD/")
        print("  2. Crea assets/mazinger/config.json")
        print("  3. Ejecuta este script para verificar instalación")
    else:
        print(f"✅ {len(themes)} temas encontrados:\n")
        
        for theme_id, info in sorted(themes.items()):
            enabled = "✅" if (info.get('enabled_by_default') and theme_id == 'mazinger_z_anime') else ""
            print(f"{enabled} [{theme_id}] {info['display_name']}")
    
    # Mostrar lista formateada para selector
    print("\n--- Lista para selector dropdown ---")
    for entry in list_themes_for_selector():
        print(f"  • {entry}")
