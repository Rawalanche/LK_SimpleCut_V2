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

import math

bl_info = {
    "name": "SimpleCut V2",
    "author": "Ludvik Koutny",
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
            self.editing = False
            self.shape = 'RECTANGLE'
            context.window_manager.modal_handler_add(self)
            bpy.context.window.cursor_set("CROSSHAIR")
            return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()

        # LMB behavior
        if event.type == 'LEFTMOUSE':

            # Press
            if event.value == 'PRESS':
                if self.editing is False:
                    self.editing = True

                    self.mouse_path = [
                        (event.mouse_region_x, event.mouse_region_y),
                        (event.mouse_region_x, event.mouse_region_y)
                    ]

                    args = (self.shape, self.mouse_path)
                    self.draw_handler = bpy.types.SpaceView3D.draw_handler_add(
                        self.draw_in_viewport, args, 'WINDOW', 'POST_PIXEL')

            # Release
            elif event.value == 'RELEASE' and self.editing is True:
                if self.shape is 'POLYGON':
                    # Compare distance from current mouse position to initial shape point
                    initial_point = Vector((self.mouse_path[0]))
                    current_point = Vector((event.mouse_region_x, event.mouse_region_y))
                    initial_point_distance = (current_point - initial_point).length

                    # Perform cut if we are close to initial point and have at least 3 points (triangle)
                    if initial_point_distance < 10 and len(self.mouse_path) > 2:
                        self.editing = False
                        self.mouse_path.pop()  # Removes last point from the mouse path
                        self.create_cutter_object(context, self.shape, self.mouse_path)
                        bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, 'WINDOW')

                    # Otherwise add one more point
                    else:
                        self.mouse_path.append((event.mouse_region_x, event.mouse_region_y))

                else:
                    self.editing = False
                    self.create_cutter_object(context, self.shape, self.mouse_path)
                    bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, 'WINDOW')

                return {'RUNNING_MODAL'}

        # Mouse move behavior
        elif event.type == 'MOUSEMOVE':
            if hasattr(self, 'mouse_path'):
                self.mouse_path[len(self.mouse_path) - 1] = (event.mouse_region_x, event.mouse_region_y)

        # RMB behavior
        elif event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if hasattr(self, 'draw_handler') and self.editing is True:
                bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, 'WINDOW')
            return {'CANCELLED'}

        # TAB behavior
        elif event.type == 'TAB' and event.value == 'PRESS' and self.editing is False:
            if self.shape == 'RECTANGLE':
                self.shape = 'POLYGON'
            elif self.shape == 'POLYGON':
                self.shape = 'CIRCLE'
            elif self.shape == 'CIRCLE':
                self.shape = 'RECTANGLE'

        else:
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def get_2d_shape(self, shape, mouse_path):
        vertices = []

        # Create 2D rectangle shape
        if shape is 'RECTANGLE':
            # Set OpenGL drawing mode to Triangle Strip
            draw_mode = 'LINE_LOOP'

            # Translate start and end of the mouse click to triangle corner coordinates
            TopLeft = (mouse_path[0][0], mouse_path[0][1])
            TopRight = (mouse_path[1][0], mouse_path[0][1])
            BottomLeft = (mouse_path[0][0], mouse_path[1][1])
            BottomRight = (mouse_path[1][0], mouse_path[1][1])

            vertices = [TopLeft, TopRight, BottomRight, BottomLeft]

        # Create 2D polygon
        elif shape is 'POLYGON':
            # Set OpenGL drawing mode to Triangle Strip
            draw_mode = 'LINE_LOOP'

            vertices = mouse_path

        # Create 2D circle shape
        elif shape is 'CIRCLE':
            # Set OpenGL drawing mode to Triangle Fan
            draw_mode = 'LINE_LOOP'

            # Length from the start and end of the mouse click to be used as circle radius
            mouse_start = Vector((mouse_path[0]))
            mouse_end = Vector((mouse_path[1]))
            radius = (mouse_end - mouse_start).length

            # Set origin of the circle to be at the mouse click start location
            origin = mouse_path[0]

            # Create triangle fan circling around center vertice
            for angle in range(0, 360, 12):
                vert = (
                    origin[0] + (math.cos(math.radians(angle)) * radius),
                    origin[1] + (math.sin(math.radians(angle)) * radius))
                vertices.append(vert)

        return (draw_mode, vertices)

    def draw_in_viewport(self, shape, mouse_path):

        # Set OpenGL settings
        bgl.glLineWidth(3)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_LINE_SMOOTH)

        # Create OpenGL shader
        shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        shader.bind()
        shader.uniform_float("color", (0.8, 0.1, 0.1, 0.5))

        # Get OpenGL draw mode and vertices to draw
        draw_mode, vertices = self.get_2d_shape(shape, mouse_path)

        # Make a shader batch and draw it
        batch = batch_for_shader(shader, draw_mode, {"pos": vertices})
        batch.draw(shader)

        # Restore OpenGL settings
        bgl.glLineWidth(1)
        bgl.glDisable(bgl.GL_BLEND)
        bgl.glDisable(bgl.GL_LINE_SMOOTH)

    def create_cutter_object(self, context, shape, mouse_path):
        """ Create a rectangle mesh """
        # Scene information
        region = context.region
        rv3d = context.region_data
        sel_obj = self.selected_object

        vertices_2d = self.get_2d_shape(shape, mouse_path)[1]

        # Calculate bbox center of selected object. Multipled by 1/8 because bound_box returns array of 8 vectors.
        local_bbox_center = 0.125 * sum((Vector(b) for b in sel_obj.bound_box), Vector())

        # Convert bbox from local to world space
        bbox_center = sel_obj.matrix_world @ local_bbox_center

        # Location and normal for the intersection plan
        plane_location = bbox_center
        plane_normal = region_2d_to_vector_3d(region, rv3d, self.mouse_path[0])

        # Create a new empty bmesh
        cutter_bmesh = bmesh.new()

        vertices_3d = []

        # Create faces from vertices and add them to the faces array
        for vertex_2d in vertices_2d:

            vertex_direction = region_2d_to_vector_3d(region, rv3d, vertex_2d)
            vertex_3d = region_2d_to_location_3d(region, rv3d, vertex_2d, vertex_direction)

            line_start = vertex_3d
            line_end = vertex_3d + (plane_normal * 10000.0)  # TODO remove magic number

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
        solidify_modifier.thickness = sum(sel_obj.dimensions)
        solidify_modifier.offset = 0.0

        self.cut_selected_object(cutter_object)

    def cut_selected_object(self, cutter_object):
        sel_obj = self.selected_object

        # Add boolean modifier to selected object and set cutter as boolean object
        boolean_modifier = sel_obj.modifiers.new(type="BOOLEAN", name="CutterBoolean")
        boolean_modifier.object = cutter_object

        # Apply boolean modifier to (currently active) selected object
        bpy.ops.object.modifier_apply(apply_as='DATA', modifier="CutterBoolean")

        # Delete cutter object
        bpy.data.objects.remove(cutter_object)


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
