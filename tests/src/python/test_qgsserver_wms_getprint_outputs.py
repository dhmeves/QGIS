"""QGIS Unit tests for QgsServer WMS GetPrint.

From build dir, run: ctest -R PyQgsServerWMSGetPrintOutputs -V


.. note:: This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

"""
__author__ = 'René-Luc DHONT'
__date__ = '24/06/2020'
__copyright__ = 'Copyright 2020, The QGIS Project'

import os

# Needed on Qt 5 so that the serialization of XML is consistent among all executions
os.environ['QT_HASH_SEED'] = '1'

import base64
import subprocess
import tempfile
import urllib.parse

import osgeo.gdal  # NOQA

from qgis.core import QgsMultiRenderChecker
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QImage, QPainter
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.testing import unittest
from test_qgsserver import QgsServerTestBase
from utilities import getExecutablePath, unitTestDataPath


class PyQgsServerWMSGetPrintOutputs(QgsServerTestBase):

    def _pdf_to_png(self, pdf_file_path, rendered_file_path, page, dpi=96):

        # PDF-to-image utility
        # look for Poppler w/ Cairo, then muPDF
        # * Poppler w/ Cairo renders correctly
        # * Poppler w/o Cairo does not always correctly render vectors in PDF to image
        # * muPDF renders correctly, but slightly shifts colors
        for util in [
            'pdftocairo',
            # 'mudraw',
        ]:
            PDFUTIL = getExecutablePath(util)
            if PDFUTIL:
                break

        # noinspection PyUnboundLocalVariable
        if not PDFUTIL:
            assert False, ('PDF-to-image utility not found on PATH: '
                           'install Poppler (with Cairo)')

        if PDFUTIL.strip().endswith('pdftocairo'):
            filebase = os.path.join(
                os.path.dirname(rendered_file_path),
                os.path.splitext(os.path.basename(rendered_file_path))[0]
            )
            call = [
                PDFUTIL, '-png', '-singlefile', '-r', str(dpi),
                '-x', '0', '-y', '0', '-f', str(page), '-l', str(page),
                pdf_file_path, filebase
            ]
        elif PDFUTIL.strip().endswith('mudraw'):
            call = [
                PDFUTIL, '-c', 'rgba',
                '-r', str(dpi), '-f', str(page), '-l', str(page),
                # '-b', '8',
                '-o', rendered_file_path, pdf_file_path
            ]
        else:
            return False, ''

        print(f"exportToPdf call: {' '.join(call)}")
        try:
            subprocess.check_call(call)
        except subprocess.CalledProcessError as e:
            assert False, ("exportToPdf failed!\n"
                           "cmd: {}\n"
                           "returncode: {}\n"
                           "message: {}".format(e.cmd, e.returncode, e.message))

    def _pdf_diff(self, pdf, control_image, max_diff, max_size_diff=QSize(), dpi=96):

        temp_pdf = os.path.join(tempfile.gettempdir(), f"{control_image}_result.pdf")

        with open(temp_pdf, "wb") as f:
            f.write(pdf)

        temp_image = os.path.join(tempfile.gettempdir(), f"{control_image}_result.png")
        self._pdf_to_png(temp_pdf, temp_image, dpi=dpi, page=1)

        control = QgsMultiRenderChecker()
        control.setControlPathPrefix("qgis_server")
        control.setControlName(control_image)
        control.setRenderedImage(temp_image)
        if max_size_diff.isValid():
            control.setSizeTolerance(max_size_diff.width(), max_size_diff.height())
        return control.runTest(control_image, max_diff), control.report()

    def _pdf_diff_error(self, response, headers, image, max_diff=100, max_size_diff=QSize(),
                        unittest_data_path='control_images', dpi=96):

        reference_path = unitTestDataPath(unittest_data_path) + '/qgis_server/' + image + '/' + image + '.pdf'
        self.store_reference(reference_path, response)

        self.assertEqual(
            headers.get("Content-Type"), 'application/pdf',
            f"Content type is wrong: {headers.get('Content-Type')} instead of application/pdf\n{response}")

        test, report = self._pdf_diff(response, image, max_diff, max_size_diff, dpi)

        with open(os.path.join(tempfile.gettempdir(), image + "_result.pdf"), "rb") as rendered_file:
            if not os.environ.get('ENCODED_OUTPUT'):
                message = f"PDF is wrong: rendered file {tempfile.gettempdir()}/{image}_result.pdf"
            else:
                encoded_rendered_file = base64.b64encode(rendered_file.read())
                message = "PDF is wrong\n{}File:\necho '{}' | base64 -d >{}/{}_result.{}".format(
                    report, encoded_rendered_file.strip().decode('utf8'), tempfile.gettempdir(), image, 'pdf'
                )

        with open(os.path.join(tempfile.gettempdir(), image + "_result.png"), "rb") as rendered_file:
            if not os.environ.get('ENCODED_OUTPUT'):
                message = f"Image is wrong: rendered file {tempfile.gettempdir()}/{image}_result.png"
            else:
                encoded_rendered_file = base64.b64encode(rendered_file.read())
                message = "Image is wrong\n{}\nImage:\necho '{}' | base64 -d >{}/{}_result.{}".format(
                    report, encoded_rendered_file.strip().decode('utf8'), tempfile.gettempdir(), image, 'png'
                )

        # If the failure is in image sizes the diff file will not exists.
        if os.path.exists(os.path.join(tempfile.gettempdir(), image + "_result_diff.png")):
            with open(os.path.join(tempfile.gettempdir(), image + "_result_diff.png"), "rb") as diff_file:
                if not os.environ.get('ENCODED_OUTPUT'):
                    message = f"Image is wrong: diff file {tempfile.gettempdir()}/{image}_result_diff.png"
                else:
                    encoded_diff_file = base64.b64encode(diff_file.read())
                    message += "\nDiff:\necho '{}' | base64 -d > {}/{}_result_diff.{}".format(
                        encoded_diff_file.strip().decode('utf8'), tempfile.gettempdir(), image, 'png'
                    )

        self.assertTrue(test, message)

    def _svg_to_png(svg_file_path, rendered_file_path, width):
        svgr = QSvgRenderer(svg_file_path)

        height = width / svgr.viewBoxF().width() * svgr.viewBoxF().height()

        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)

        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        svgr.render(p)
        p.end()

        res = image.save(rendered_file_path, 'png')
        if not res:
            os.unlink(rendered_file_path)

    """QGIS Server WMS Tests for GetPrint request with non default outputs"""

    def test_wms_getprint_basic(self):

        # Output JPEG
        qs = "?" + "&".join(["%s=%s" % i for i in list({
            "MAP": urllib.parse.quote(self.projectPath),
            "SERVICE": "WMS",
            "VERSION": "1.1.1",
            "REQUEST": "GetPrint",
            "TEMPLATE": "layoutA4",
            "FORMAT": "jpeg",
            "map0:EXTENT": "-33626185.498,-13032965.185,33978427.737,16020257.031",
            "LAYERS": "Country,Hello",
            "CRS": "EPSG:3857"
        }.items())])

        r, h = self._result(self._execute_request(qs))
        self._img_diff_error(r, h, "WMS_GetPrint_Basic", outputFormat='JPG')

        # Output PDF
        qs = "?" + "&".join(["%s=%s" % i for i in list({
            "MAP": urllib.parse.quote(self.projectPath),
            "SERVICE": "WMS",
            "VERSION": "1.1.1",
            "REQUEST": "GetPrint",
            "TEMPLATE": "layoutA4",
            "FORMAT": "pdf",
            "map0:EXTENT": "-33626185.498,-13032965.185,33978427.737,16020257.031",
            "LAYERS": "Country,Hello",
            "CRS": "EPSG:3857"
        }.items())])

        r, h = self._result(self._execute_request(qs))
        self._pdf_diff_error(r, h, "WMS_GetPrint_Basic_Pdf", dpi=300)

    def test_wms_getprint_selection(self):

        # Output PDF
        qs = "?" + "&".join(["%s=%s" % i for i in list({
            "MAP": urllib.parse.quote(self.projectPath),
            "SERVICE": "WMS",
            "VERSION": "1.1.1",
            "REQUEST": "GetPrint",
            "TEMPLATE": "layoutA4",
            "FORMAT": "pdf",
            "LAYERS": "Country,Hello",
            "map0:EXTENT": "-33626185.498,-13032965.185,33978427.737,16020257.031",
            "map0:LAYERS": "Country,Hello",
            "CRS": "EPSG:3857",
            "SELECTION": "Country: 4"
        }.items())])

        r, h = self._result(self._execute_request(qs))
        self._pdf_diff_error(r, h, "WMS_GetPrint_Selection_Pdf", dpi=300)


if __name__ == '__main__':
    unittest.main()
