# system
import numpy as np
import cv2
import os

# director
import director.vtkAll as vtk
import director.vtkNumpy as vnp
from director import mainwindowapp
import director.visualization as vis
from director import screengrabberpanel as sgp

# pdc
from dense_correspondence_manipulation.fusion.fusion_reconstruction import FusionReconstruction, TSDFReconstruction
from dense_correspondence.dataset.dataset_structure import DatasetStructure
import dense_correspondence_manipulation.utils.director_utils as director_utils
import dense_correspondence_manipulation.utils.utils as utils

"""
Class to colorize the mesh for later rendering
"""

SQUARED_255 = 65025

class MeshColorizer(object):

    def __init__(self, poly_data_item):
        self._poly_data_item = poly_data_item
        self._poly_data = poly_data_item.polyData

    def add_colors_to_mesh(self):
        """
        Adds the colors the mesh by creating the array and adding it to the
        CellData for the poly data
        :return:
        :rtype:
        """

        num_cells = self._poly_data.GetNumberOfCells()
        color_array = self.make_vtk_color_array(num_cells)
        array_name = 'cell colors'
        color_array.SetName(array_name)
        self._poly_data.GetCellData().AddArray(color_array)
        self._poly_data.GetCellData().SetActiveScalars(array_name)

        self._poly_data_item.mapper.ScalarVisibilityOn()
        # self._poly_data_item.setProperty('Surface Mode', 'Surface with edges')
        self._poly_data_item._renderAllViews() # render all the views just to be safe

    @staticmethod
    def index_to_color(idx):
        """
        Converts an integer (idx+1) into a base 255 representation
        Can handle numbers up to 255**3 - 1 = 16581374

        We don't want to use color (0,0,0) since that is reserved for the background

        Color is assumed to be in (r,g,b) format

        :param idx: The integer index to convert
        :type idx: int or long
        :return:
        :rtype:
        """
        base = 2
        idx_str = np.base_repr(idx+1, base=base)

        # 24 because it is 3 * 8, and 255 = 2**8
        idx_str = str(idx_str).zfill(24)

        r_str = idx_str[0:8]
        g_str = idx_str[8:16]
        b_str = idx_str[16:24]

        rgb = (int(r_str, base), int(g_str, base), int(b_str, base))

        return rgb


    @staticmethod
    def color_to_index(color):
        """
        Converts a color (r,g,b) with r,g,b \in [0,255] back to an index
        The color is the representation of the index in base 255.

        Note 65025 = 255**2
        :param color: (r,g,b) color representation
        :type color: list(int) with length 3
        :return: int
        :rtype:
        """


        idx = SQUARED_255 * color[0] + 255 * color[1] + color[2]
        idx -= - 1 #subtract one to account for the fact that the background is idx 0
        return idx

    @staticmethod
    def rgb_img_to_idx_img(rgb_image):
        """

        :param rgb_image: [H,W,3] image in (r,g,b) format
        :type rgb_image: numpy.ndarray
        :return: numpy.array [H,W] with dtype = uint64
        :rtype:
        """

        # cast to int64 to avoid overflow
        idx_img = np.array(rgb_image, dtype=np.int64)
        idx_img = idx_img[:,:,0] * SQUARED_255 + idx_img[:,:,1]*255 + idx_img[:,:,2]
        idx_img -= 1 # subtract 1 because previously the background was 0

    @staticmethod
    def make_color_array(num_cells):
        """
        Makes a color array with the given number of rows
        :param num_cells:
        :type num_cells:
        :return:
        :rtype:
        """

        a = np.zeros([num_cells, 3], dtype=np.uint8)
        for i in xrange(0, num_cells):
            a[i,:] = np.array(MeshColorizer.index_to_color(i))

        return a

    @staticmethod
    def make_vtk_color_array(num_cells):
        """
        Makes a color array with the given number of rows
        :param num_cells:
        :type num_cells:
        :return: vtkUnsignedCharacterArray
        :rtype:
        """
        a = vtk.vtkUnsignedCharArray()
        a.SetNumberOfComponents(3)
        a.SetNumberOfTuples(num_cells)

        for i in xrange(0, num_cells):
            a.InsertTuple(i, MeshColorizer.index_to_color(i))

        return a


class MeshRender(object):

    def __init__(self, view, view_options, fusion_reconstruction, data_folder):
        """
        app is the director app
        :param view: app.view
        :type view:
        :param self._view_options: app.self._view_options
        :type self._view_options:
        """

        self._view = view
        self._view_options = view_options
        self._fusion_reconstruction = fusion_reconstruction
        self._poly_data_item = self._fusion_reconstruction.vis_obj

        # list of vis objects to control the lighting on
        self._vis_objects = []
        self._vis_objects.append(self._poly_data_item)

        # colorize the mesh
        self._mesh_colorizer = MeshColorizer(self._poly_data_item)
        self._mesh_colorizer.add_colors_to_mesh()

        self._data_folder = data_folder
        self._dataset_structure = DatasetStructure(data_folder)

        self.initialize()


    def initialize(self):
        """
        Visualizes the fusion reconstruction.
        Sets the camera intrinsics etc.
        :return:
        :rtype:
        """
        self.set_camera_intrinsics()

    def set_camera_intrinsics(self):
        """
        Sets the camera intrinsics, and locks the view size
        :return:
        :rtype:
        """

        self._camera_intrinsics = utils.CameraIntrinsics.from_yaml_file(self._dataset_structure.camera_info_file)
        director_utils.setCameraIntrinsics(self._view, self._camera_intrinsics, lockViewSize=True)

    def set_camera_transform(self, camera_transform):
        """
        Sets the camera transform and forces a render
        :param camera_transform: vtkTransform
        :type camera_transform:
        :return:
        :rtype:
        """
        director_utils.setCameraTransform(self._view.camera(), camera_transform)
        self._view.forceRender()

    def render_images(self):
        """
        Render images of the colorized mesh
        Creates files processed/rendered_images/000000_mesh_cells.png
        :return:
        :rtype:
        """

        self.disable_lighting()

        image_idx_list = self._fusion_reconstruction.get_image_indices()
        num_poses = len(image_idx_list)


        for counter, idx in enumerate(image_idx_list):
            print "Rendering mask for pose %d of %d" % (counter + 1, num_poses)
            camera_to_world = self._fusion_reconstruction.get_camera_to_world(idx)
            self.set_camera_transform(camera_to_world)
            filename = self._dataset_structure.mesh_cells_image_filename(idx)

            img, img_vtk = self.render_image(filename=filename)


    def disable_lighting(self):
        """
        Disables the lighting.
        Sets the background to black (i.e. (0,0,0))
        :return:
        :rtype:
        """
        self._view_options.setProperty('Gradient background', False)
        self._view_options.setProperty('Orientation widget', False)
        self._view_options.setProperty('Background color', [0, 0, 0])

        self._view.renderer().TexturedBackgroundOff()

        for obj in self._vis_objects:
            obj.actor.GetProperty().LightingOff()

        self._view.forceRender()

    def render_image(self, filename=None):
        """
        Make sure you call disable_lighting() BEFORE calling this function
        :return:
        :rtype:
        """

        img_vtk = sgp.saveScreenshot(self._view, filename, shouldRender=True, shouldWrite=True)

        img = vnp.getNumpyFromVtk(img_vtk, arrayName='ImageScalars')
        assert img.dtype == np.uint8

        img.shape = (img_vtk.GetDimensions()[1], img_vtk.GetDimensions()[0], 3)
        img = np.flipud(img)

        # if filename is not None:
        #     cv2.imwrite(filename, img)

        return img, img_vtk

    def test(self):
        filename = os.path.join("/home/manuelli/code/sandbox", "test.png")
        return self.render_image(filename=filename)

    @staticmethod
    def from_data_folder(data_folder, config=None):
        """
        Creates the director app
        Creates a MeshRender object from the given folder

        :param data_folder:
        :type data_folder:
        :type config:
        :return:
        :rtype:
        """

        # dict to store objects that are created
        obj_dict = dict()

        # create the director app
        # make sure we disable anti-aliasing

        vis.setAntiAliasing(False)
        app = mainwindowapp.construct()
        app.gridObj.setProperty('Visible', False)
        app.viewOptions.setProperty('Orientation widget', False)
        app.viewOptions.setProperty('View angle', 30)
        app.sceneBrowserDock.setVisible(False)
        app.propertiesDock.setVisible(False)
        app.mainWindow.setWindowTitle('Mesh Rendering')

        app.mainWindow.show()
        app.mainWindow.resize(920, 600)
        app.mainWindow.move(0, 0)

        foreground_reconstruction = TSDFReconstruction.from_data_folder(data_folder, load_foreground_mesh=True)
        foreground_reconstruction.visualize_reconstruction(app.view)

        mesh_render = MeshRender(app.view, app.viewOptions, foreground_reconstruction, data_folder)


        obj_dict['app'] = app
        obj_dict['foreground_reconstruction'] = foreground_reconstruction
        obj_dict['mesh_render'] = mesh_render

        return obj_dict