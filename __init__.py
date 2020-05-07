# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import bpy
from bpy.props import FloatVectorProperty
from bpy_extras import view3d_utils
from bpy_extras.view3d_utils import (
    region_2d_to_vector_3d,
    region_2d_to_location_3d,
    location_3d_to_region_2d,
)

import bgl
import blf
import gpu
import bmesh
from gpu_extras.batch import batch_for_shader

from mathutils import Vector
from mathutils.geometry import (
    intersect_line_plane,
)


bl_info = {
    "name": "SimpleCut V2",
    "author": "Ludvik Koutny, Pixivore, Cedric LEPILLER, Ted Milker, Clarkx",
    "description": "A simple tool to cut meshes using boolean operations",
    "version": (1, 2, 0),
    "blender": (2, 80, 0),
    "location": "Hotkey needs to be assigned by user",
    "category": "Object"
}


class SimpleCut(bpy.types.Operator):
    """Translate the view using mouse events"""
    bl_idname = "simplecut.operator"
    bl_label = "SimpleCut Operator"

    def invoke(self, context, event):

        if len(context.selected_objects) == 0:
            self.report({'WARNING'}, "No mesh object selected!")
            return {'CANCELLED'}
        elif context.space_data.type != 'VIEW_3D':
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}
        else:
            self.selected_object = context.active_object
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self.mouse_path = [
                    (event.mouse_region_x, event.mouse_region_y),
                    (event.mouse_region_x, event.mouse_region_y)
                ]

                args = (self, context)
                self.draw_handler = bpy.types.SpaceView3D.draw_handler_add(DrawInViewport, args, 'WINDOW', 'POST_PIXEL')

            elif event.value == 'RELEASE':
                Cut(self, context)
                bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, 'WINDOW')
                return {'FINISHED'}

        elif event.type == 'MOUSEMOVE':
            if hasattr(self, 'mouse_path'):
                self.mouse_path[1] = (event.mouse_region_x, event.mouse_region_y)

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, 'WINDOW')
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}


def Cut(self, context):
    """ Create a rectangle mesh """
    # Scene information
    region = context.region
    rv3d = context.region_data

    if len(self.mouse_path) > 0:
        TopLeft = (self.mouse_path[0][0], self.mouse_path[0][1])
        TopRight = (self.mouse_path[1][0], self.mouse_path[0][1])
        BottomLeft = (self.mouse_path[0][0], self.mouse_path[1][1])
        BottomRight = (self.mouse_path[1][0], self.mouse_path[1][1])

    vertices_2d = (
        TopLeft,
        TopRight,
        BottomRight,
        BottomLeft,
    )

    # Create a new empty bmesh
    cutter_bmesh = bmesh.new()

    plane_normal = region_2d_to_vector_3d(region, rv3d, self.mouse_path[0])
    plane_location = Vector((0.0, 0.0, 0.0))
    vertices_3d = []

    # Create faces from vertices and add them to the faces array
    for vertex_2d in vertices_2d:

        vertex_direction = region_2d_to_vector_3d(region, rv3d, vertex_2d)
        vertex_3d = region_2d_to_location_3d(region, rv3d, vertex_2d, vertex_direction)

        line_start = vertex_3d
        line_end = vertex_3d + (plane_normal * 10000.0)

        vertex_intersection = intersect_line_plane(line_start, line_end, plane_location, plane_normal)
        vertices_3d.append(cutter_bmesh.verts.new(vertex_intersection))

    # Update vertices index
    cutter_bmesh.verts.index_update()

    # New faces
    cutter_bmesh.faces.new(vertices_3d)

    # Create new empty mesh
    mesh = bpy.data.meshes.new('SM_Cutter')

    # Add bmesh data to the created empty mesh
    cutter_bmesh.to_mesh(mesh)

    # Create new object from the mesh and add it to the active collection
    cutter_object = bpy.data.objects.new('Cutter', mesh)
    context.collection.objects.link(cutter_object)

    # Add solidify modifier to cutter object and set its thickness
    solidify_modifier = cutter_object.modifiers.new(type="SOLIDIFY", name="CutterSolidify")
    solidify_modifier.thickness = 1.0

    # Add boolean modifier to selected object and set cutter as boolean object
    boolean_modifier = self.selected_object.modifiers.new(type="BOOLEAN", name="CutterBoolean")
    boolean_modifier.object = cutter_object

    # Apply boolean modifier to (currently active) selected object
    bpy.ops.object.modifier_apply(apply_as='DATA', modifier="CutterBoolean")

    # Delete cutter object
    bpy.data.objects.remove(cutter_object)


def DrawInViewport(self, context):
    bgl.glLineWidth(2)
    bgl.glEnable(bgl.GL_BLEND)
    bgl.glEnable(bgl.GL_LINE_SMOOTH)

    shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
    shader.bind()
    shader.uniform_float("color", (0.8, 0.1, 0.1, 0.5))

    TopLeft = (self.mouse_path[0][0], self.mouse_path[0][1])
    TopRight = (self.mouse_path[1][0], self.mouse_path[0][1])
    BottomLeft = (self.mouse_path[0][0], self.mouse_path[1][1])
    BottomRight = (self.mouse_path[1][0], self.mouse_path[1][1])

    verts = (
        TopLeft,
        TopRight,
        BottomRight,
        BottomLeft,
    )

    batch = batch_for_shader(shader, 'LINE_LOOP', {"pos": verts})

    batch.draw(shader)

    # restore opengl defaults
    bgl.glLineWidth(1)
    bgl.glDisable(bgl.GL_BLEND)
    bgl.glDisable(bgl.GL_LINE_SMOOTH)


addon_keymaps = []


def register():
    bpy.utils.register_class(SimpleCut)
    kcfg = bpy.context.window_manager.keyconfigs.addon
    if kcfg:
        km = kcfg.keymaps.new(name='3D View', space_type='VIEW_3D')
        kmi = km.keymap_items.new("simplecut.operator", 'V', 'PRESS')
        addon_keymaps.append((km, kmi))


def unregister():
    bpy.utils.unregister_class(SimpleCut)
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
