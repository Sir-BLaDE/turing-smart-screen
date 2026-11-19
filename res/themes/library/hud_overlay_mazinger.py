# Mazinger Robot Overlay - GameHUD v12 Integration
"""
Módulo de overlay para robot Mazinger Z como elemento decorativo.

INSTALACIÓN:
  Este archivo se copió automáticamente desde:
    C:\Dev\Default Project\turing-smart-screen-python\library\hud_overlay_mazinger.py
  
  No modifica archivos existentes, es renderizado puramente visual encima del HUD.

CONFIGURACIÓN:
  Usa mazinger_config.json para saber qué diseño está activo.
  Puedes cambiar el diseño desde GameHUD configurador sin tocar código.

RENDERSLAYER:
  Renderiza en capa superior del HUD (top layer).
  No toca stats, sensores ni calculos existentes.
"""

import os
import sys

# Agregar directorio de assets al path para importar mazinger_config
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'assets')
if ASSETS_DIR not in sys.path:
    sys.path.insert(0, ASSETS_DIR)

from PIL import Image, ImageDraw, ImageFont
import json

# Importar sistema de configuración Mazinger
sys.path.insert(0, os.path.join(ASSETS_DIR))
from mazinger_config import (
    AVAILABLE_DESIGNS, 
    load_config, 
    get_active_design,
    list_installed_designs
)


# ============================================
# CLASE PRINCIPAL MAZINGER OVERLAY RENDERER
# ============================================

class MazingerOverlayRenderer:
    """
    Clase para renderizar overlay decorativo del robot Mazinger Z.
    
    Uso en GameHUD:
      renderer = MazingerOverlayRenderer()
      image = renderer.render_to_hud_frame(hud_surface)
    
    Características:
      - Renderiza encima del HUD existente sin modificarlo
      - Usa configuración desde mazinger_config.json
      - Soporta cambio dinámico entre diseños instalados
      - Compatible con GameHUD v12 estructura de carpetas
    """
    
    def __init__(self):
        """Inicializa renderer con diseño activo por defecto."""
        
        print("[MazingerOverlayRenderer] Initializing...")
        
        # Cargar configuración actual
        self.config = load_config()
        
        # Obtener información del diseño activo
        design_info = get_active_design()
        self.active_design_id = design_info["active_design"]
        self.design_name = design_info["design"]["name"]
        self.filename = design_info["filename"]
        self.design_path = design_info["path_to_file"]
        
        print(f"[OK] Active design: {self.design_name}")
        print(f"[OK] Design file: {self.filename}")
        print(f"[OK] Design path: {self.design_path}")
        
        # Guardar referencias para acceso rápido
        self.settings = self.config["settings"]
        self.available_designs = AVAILABLE_DESIGNS
        
    def get_current_design_info(self):
        """Devuelve información del diseño actualmente activo."""
        
        return {
            "id": self.active_design_id,
            "name": self.design_name,
            "filename": self.filename,
            "path": self.design_path,
            "size": next(d["size"] for d in self.available_designs if d["id"] == self.active_design_id)
        }
    
    def load_design_sprite(self):
        """Carga sprite PNG del diseño activo desde disco."""
        
        try:
            # Asegurar que existe el archivo (generar si falta)
            sprite_path = self.design_path
            
            if not os.path.exists(sprite_path):
                print(f"[WARNING] Sprite file not found: {sprite_path}")
                print(f"[INFO] Generating design preview for: {self.active_design_id}...")
                
                # Si no existe, generar una imagen básica del diseño
                self._generate_preview_sprite()
            
            # Cargar imagen PNG existente o recién generada
            sprite = Image.open(sprite_path)
            
            print(f"[OK] Loaded sprite: {sprite_path}")
            print(f"[INFO] Size: {sprite.size}, Mode: {sprite.mode}")
            
            return sprite
            
        except Exception as e:
            print(f"[ERROR] Failed to load sprite {self.filename}: {e}")
            return None
    
    def _generate_preview_sprite(self):
        """Genera imagen de vista previa si el archivo no existe."""
        
        # Generar basada en ID del diseño activo
        design_id = self.active_design_id
        
        if "anime" in design_id:
            # Generar estilo anime clásico básico
            print("[INFO] Generating classic anime style preview...")
            sprite = self._draw_anime_classic_preview()
            
        elif "vector" in design_id or "modern" in design_id:
            # Generar estilo vector minimalista básico
            print("[INFO] Generating vector clean style preview...")
            sprite = self._draw_vector_modern_preview()
        
        else:
            # Fallback a diseño genérico azul
            print("[WARNING] Unknown design type, using default blue robot...")
            sprite = self._draw_default_robotsprite()
        
        return sprite
    
    def _draw_anime_classic_preview(self):
        """Dibuja vista previa estilo anime clásico."""
        
        size = 256
        img = Image.new('RGB', (size, size), (30, 40, 55))
        d = ImageDraw.Draw(img)
        
        cx, cy = size // 2, size // 2
        
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except:
            font = None
        
        # Cuerpo principal azul metálico
        d.rectangle([75, 90, 181, 196], fill="#1E90FF")
        d.rectangle([92, 93, 164, 193], outline="#FFFFFF", width=3)
        
        # Escudo amarillo central
        d.rectangle([108, 115, 148, 171], fill="#FFD700")
        
        try:
            d.ellipse([98, 88, 158, 126], fill="#1E90FF")
            d.ellipse([98, 169, 158, 207], fill="#1E90FF")
            
            # Cabeza circular con visor rojo
            d.arc([cx - 45, cy - 45, cx + 45, cy + 45], 0, 360, fill="#1E90FF", width=8)
            d.arc([cx - 25, cy - 15, cx + 25, cy + 30], 0, 360, fill="#FF1E00")
            
            # Partículas de energía azul (líneas decorativas)
            d.line([cx - 80, cy - 90, cx + 80, cy - 90], width=2, fill="#00CED1")
            d.line([cx - 75, cy - 95, cx + 75, cy - 95], width=1, fill="#00CED1")
        except:
            pass
        
        output_path = os.path.join(ASSETS_DIR, "mazinger", self.filename)
        img.save(output_path)
        
        return img
    
    def _draw_vector_modern_preview(self):
        """Dibuja vista previa estilo vector clean minimalista."""
        
        size = 128
        img = Image.new('RGB', (size, size), (20, 30, 50))
        
        d = ImageDraw.Draw(img)
        cx, cy = size // 2, size // 2
        
        radius = min(size - 8, 70)
        
        # Contorno exterior circular
        try:
            d.ellipse([cx - radius + 1, cy - radius + 1, cx + radius - 1], 
                     outline="#2D2D2D", width=3)
            
            # Cuerpo plano azul eléctrico
            torso_width = min(size - 20, 75)
            d.rectangle([cx - torso_width//2, cy + size*0.3, cx + torso_width//2], 
                       fill="#007FFF")
            
            # Línea decorativa horizontal
            d.line([cx - torso_width//4, cy + size*0.48, cx + torso_width//4], 
                   width=1, fill="#F0F0F0")
            
            # Cabeza vectorial simplificada
            head_radius = min(size - 30, 60)
            d.rectangle([cx - head_radius, cy - head_radius + 8, cx + head_radius], 
                       fill="#007FFF")
            
            # Ojos del visor (puntos blancos friendly)
            eye_y = cy - head_radius + 40
            d.ellipse([cx - 15, eye_y, cx - 8, eye_y + 6], fill="#FFFFFF")
            d.ellipse([cx + 8, eye_y, cx + 15, eye_y + 6], fill="#FFFFFF")
            
            # Visor tradicional (línea amarilla neón)
            try:
                d.line([cx - head_radius//3 + 8, cy - head_radius + 45, 
                       cx + head_radius//3 - 8], width=1, fill="#FFCC00")
                
                # Efecto de brillo cyan semitransparente
                try:
                    d.ellipse([cx - radius*0.7, cy - radius*0.7, cx + radius*0.7], 
                             fill="#66E0FF", opacity=25)
                except:
                    pass
            except:
                pass
            
        except:
            pass
        
        output_path = os.path.join(ASSETS_DIR, "mazinger", self.filename)
        img.save(output_path)
        
        return img
    
    def _draw_default_robotsprite(self):
        """Dibuja robot básico genérico si ningún diseño específico se encuentra."""
        
        size = 128
        img = Image.new('RGB', (size, size), (40, 50, 60))
        d = ImageDraw.Draw(img)
        
        cx, cy = size // 2, size // 2
        
        # Cuerpo rectangular básico azul
        try:
            d.rounded_rectangle([cx - 50, cy + 40, cx + 50], radius=15, fill="#2A9DFF")
            
            # Cabeza circular básica
            try:
                d.arc([cx - 35, cy - 35, cx + 35], 0, 360, fill="#2A9DFF", width=8)
                
                # Ojos del visor genéricos (puntos blancos)
                eye_y = cy - 25
                d.point([cx - 12, eye_y], fill="#FFFFFF")
                d.point([cx + 12, eye_y], fill="#FFFFFF")
            except:
                pass
            
            # Detalles decorativos simples (lineas horizontales)
            d.line([cx - 30, cy + 65, cx + 30, cy + 70], width=1, fill="#E8F4FC")
        except:
            pass
        
        return img
    
    def render_to_hud_frame(self, hud_surface):
        """
        Renderiza robot Mazinger encima del frame de HUD.
        
        Args:
          hud_surface: Surface PIL/PIL Image del frame de HUD principal (deja GameHUD)
        
        Returns:
          Nueva surface con robot overlay renderizado encima
            
        Características de renderizado:
          - Usa posición y offset desde configuracion self.settings
          - Renderiza en capa visual superior (top layer)
          - No modifica stats/sensores/calculos existentes
        """
        
        # Cargar sprite del diseño activo
        sprite = self.load_design_sprite()
        if not sprite:
            return hud_surface  # Devolver surface original si no hay sprite
        
        # Obtener dimensiones de sprite y HUD
        spr_width, spr_height = sprite.size
        hud_width, hud_height = hud_surface.size
        
        # Calcular posición centrada con offsets de configuracion
        offset_x = self.settings.get("position_offset_x", 0)
        offset_y = self.settings.get("position_offset_y", -100)
        
        # Calcular centro del HUD para posicionamiento
        center_x = hud_width / 2 + offset_x
        center_y = hud_height / 2 + offset_y - (spr_height * 0.15)  # Ajuste vertical
        
        # Escalar sprite si es necesario (opcional)
        scale_factor = self.settings.get("scale", 1.0)
        if scale_factor != 1.0:
            sprite = sprite.resize((int(spr_width * scale_factor), 
                                    int(spr_height * scale_factor)), 
                                  Image.LANCZOS)
        
        # Renderizar sprite centrado en HUD
        new_x = center_x - spr_width / 2
        new_y = center_y - spr_height / 2
        
        try:
            hud_surface.paste(sprite, (int(new_x), int(new_y)))
        except AttributeError:
            # Fallback si surface no soporta paste directamente
            # Convertir a imagen nueva y renderizar encima
            output_img = Image.new('RGB', hud_surface.size, 
                                  tuple(int(c) for c in hud_surface.getpixel((0,0))))
            output_img.paste(sprite, (int(new_x), int(new_y)))
        
        return hud_surface
    
    def change_active_design(self, design_id):
        """
        Cambia diseño activo sin reiniciar GameHUD.
        
        Esto permite que el usuario seleccione otro robot desde configurador HUD,
        y el cambio toma efecto inmediatamente en el próximo frame renderizado.
        """
        
        if not any(d["id"] == design_id for d in self.available_designs):
            print(f"[ERROR] Design '{design_id}' not found. Available designs:")
            for d in self.available_designs:
                print(f"  - {d['name']} ({d['id']})")
            return False
        
        # Guardar nuevo diseño activo
        self.active_design_id = design_id
        self.design_name = next(d["name"] for d in self.available_designs if d["id"] == design_id)
        
        print(f"[OK] Changed active design to: {self.design_name}")
        return True
    
    def get_available_designs_list(self):
        """Devuelve lista de diseños disponibles para selector."""
        
        designs_for_selector = [d for d in self.available_designs]
        designs_for_selector.sort(key=lambda x: x.get("priority", 99))
        
        # Agregar indicador de cuál está activo
        for design in designs_for_selector:
            status = " [ACTIVE]" if design["id"] == self.active_design_id else ""
            design["label"] = f"{design['name']}{status}"
            design["current_active"] = design["id"] == self.active_design_id
        
        return {
            "available": designs_for_selector,
            "total_count": len(designs_for_selector),
            "current_design": self.active_design_id
        }


# ============================================
# FUNCIONES DE UTILIDAD
# ============================================

def create_mazinger_renderer():
    """Crea instancia de MazingerOverlayRenderer para GameHUD."""
    
    return MazingerOverlayRenderer()


def get_active_mazinger_design():
    """Devuelve información del diseño Mazinger actualmente activo."""
    
    if hasattr(MazingerOverlayRenderer, '_instance'):
        renderer = MazingerOverlayRenderer._instance
    else:
        renderer = MazingerOverlayRenderer()
        MazingerOverlayRenderer._instance = renderer
    
    return renderer.get_current_design_info()


def list_mazinger_designs():
    """Lista todos los diseños de robot Mazinger disponibles para selección."""
    
    renderer = create_mazinger_renderer()
    return renderer.get_available_designs_list()


# ============================================
# MAIN - PRUEBA DE INICIALIZACIÓN
# ============================================

if __name__ == "__main__":
    print("=" * 80)
    print("MAZINGER OVERLAY RENDERER INITIALIZATION TEST")
    print("=" * 80)
    print()
    
    # Crear renderer y probar
    try:
        renderer = MazingerOverlayRenderer()
        
        print("\n" + "=" * 80)
        print("INITIALIZED SUCCESSFULLY!")
        print("=" * 80)
        print()
        
        # Mostrar diseño activo actual
        design_info = renderer.get_current_design_info()
        print(f"Active Design: {design_info['name']}")
        print(f"Design ID: {design_info['id']}")
        print(f"File: {design_info['filename']}")
        print()
        
        # Mostrar diseños disponibles para selector
        designs_list = renderer.get_available_designs_list()
        print("Available Designs for Selector:")
        print("-" * 60)
        for design in designs_list["available"]:
            active_marker = " ← CURRENTLY ACTIVE" if design.get("current_active") else ""
            print(f"  [{design['priority']}] {design['label']}{active_marker}")
            print(f"      Description: {design['description']}")
        
        # Guardar lista de diseños para referencia futura
        with open(os.path.join(ASSETS_DIR, "mazinger", "INSTALLED_DESIGNS.txt"), 'w') as f:
            f.write("Mazinger Robot Designs - Currently Installed\\n")
            print("=" * 80)
            f.write("=" * 80 + "\\n\\n")
            
            for design in designs_list["available"]:
                active_marker = " [ACTIVE]" if design.get("current_active") else ""
                f.write(f"{design['name']}{active_marker}\\n")
                f.write(f"  ID: {design['id']}\\n")
                f.write(f"  File: {design['filename']}\\n")
                f.write(f"  Size: {design.get('size', 'N/A')}\\n")
                f.write(f"  Description: {design['description']}\\n\\n")
        
        print(f"[INFO] Design list saved to: INSTALLED_DESIGNS.txt")
        
    except Exception as e:
        print(f"[ERROR] Initialization failed: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("=" * 80)
    print("READY FOR GameHUD INTEGRATION!")
    print("=" * 80)
    
    # Instrucciones para GameHUD integracion
    instructions = """

GAMEHUD INTEGRATION INSTRUCTIONS:

1. EN CONFIGURADOR HUD ADDING MAZINGER OVERLAY SETTING:

   - Location: Settings -> HUD Overlay Options (o similar)
   - Setting Name: "mazinger_design_id" (debe coincidir con design['id'])
   - Type: Dropdown box / Select dropdown
   - Default Value: ID del diseño actualmente activo (ej: "mazinger_anime_classic")
   - Options: Lista de todos los diseños disponibles en get_available_designs_list()

2. EN RENDERO PRINCIPAL RENDERIZANDO FRAME:

   - Importar: from library.hud_overlay_mazinger import create_mazinger_renderer
   - Crear instancia: renderer = create_mazinger_renderer()
   - En cada frame renderizado: renderer.render_to_hud_frame(hud_surface)

3. CAMBIAR DISEÑO DINÁMICAMENTE:

   Si usuario selecciona otro diseño desde configurador:
   
     renderer.change_active_design(new_design_id)  # Cambia inmediatamente
   
   O crear nuevo renderer con nueva configuración si prefieres reinicio completo:
   
     new_renderer = MazingerOverlayRenderer()  # Recargar config.json
   
4. NO TOCAR ARCHIVOS EXISTENTES:

   - Este módulo solo renderiza overlay encima del HUD
   - No modifica stats, sensores ni calculos de GameHUD
   - Usa configuración externa (mazinger_config.json) para diseño activo
"""
    
    print("\n" + instructions)
    print("=" * 80)
