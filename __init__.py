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

        if context.space_data.type == 'VIEW_3D':
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}

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

    # Get a point on a infinite plane and its direction
    plane_normal = region_2d_to_vector_3d(region, rv3d, self.mouse_path[0])

    plane_location = Vector((0.0, 0.0, 0.0))

    faces = []

    # New mesh
    mesh = bpy.data.meshes.new('CMT_Square')
    cut_bmesh = bmesh.new()
    cut_bmesh.from_mesh(mesh)

    # New object and link it to the scene
    ob = bpy.data.objects.new('CMT_Square', mesh)
    context.collection.objects.link(ob)

    # Find the intersection of a line going thru each vertex and the infinite plane
    for v_co in verts:
        vec = region_2d_to_vector_3d(region, rv3d, v_co)
        p0 = region_2d_to_location_3d(region, rv3d, v_co, vec)
        p1 = region_2d_to_location_3d(region, rv3d, v_co, vec) + plane_normal * 10000.0
        faces.append(cut_bmesh.verts.new(intersect_line_plane(p0, p1, plane_location, plane_normal)))

    # Update vertices index
    cut_bmesh.verts.index_update()
    # New faces
    t_face = cut_bmesh.faces.new(faces)

    # Set mesh
    cut_bmesh.to_mesh(mesh)


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
