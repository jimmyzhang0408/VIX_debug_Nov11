import json
import time
import datetime
import websocket  # websocket is used for communicating with the device over the network.  pip install websocket-client
import uuid
# QT5 libraries are used to create the GUI.

from PyQt5.QtCore import Qt
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5 import QtGui

import numpy as np  # numpy is used as part of spectrum drawing      // pip install numpy
import pyqtgraph as pg  # pyqtgraph is used to display the spectrum data // pip install pyqtgraph

""" 
    WebSocketThread creates the websocket connection  and then listens for the messages coming through.
    If we get data we send it using the notification signal. 
"""


class WebSocketThread(QThread):
    verbose = False  # Set to true if you want to see what is going on.
    notification = pyqtSignal(dict)

    # noinspection PyTypeChecker
    def send_command(self, command):
        """This function actually dispatches the json command to the host."""
        if self.ws.connected:
            command["id"] = self.parent.next_command_id()  # Tag each command with a new ID.
            if self.verbose:
                print("Sending ", json.dumps(command))
            result = self.ws.send_binary(json.dumps(command))  # IMPORTANT data is sent as BINARY not text.
            if self.verbose:
                print(result)

            time.sleep(0.05)
        else:
            if self.verbose:
                print("Cannot send command. Disconnected!")

    def create_connection(self, web_socket, host, controller):
        """ connect to the supplied host using the supplied websocket. If we want to listen controller = false"""
        try:
            web_socket.connect(host)
        except Exception as e:
            print(repr(e))
            print("Unable to connect")
            return False
        print("Connected=", web_socket.connected)

        if web_socket.connected and controller:  # connect as a controller
            command = "Hi i am a controller"
            result = web_socket.send(command)  # IMPORTANT that the data here is sent as TEXT. (See send_command)
            print("Sent ", command, "Result=", result)

            result = web_socket.recv()
            print("Response=", result)
            if result == "Server ready to receive commands.":
                return True
            else:
                return False
        else:  # connect as a listener

            command = "Hi i am a listener"
            result = web_socket.send(command)  # IMPORTANT that the data here is sent as TEXT.(See send_command)
            print("Sent ", command, "Result=", result)

            result = web_socket.recv()
            print("Response=", result)
            if result == "Client connected as a listener.":
                return True
            else:
                return False

    def listen(self, web_socket):
        """ Keep listening on the websocket connection for data coming in.
            If we get data send it as a notification signal"""
        while 1:
            if web_socket.connected:
                try:
                    result = web_socket.recv()
                    if self.verbose:
                        print(result, )
                    data = json.loads(result)
                    self.notification.emit(data)
                except Exception as e:
                    print(repr(e))
                    print(".")
                time.sleep(0.01)
            else:
                time.sleep(1)
                self.create_connection(self.ws, self.host, self.controller)

    def __init__(self, parent, host, controller):
        self.host = host
        self.controller = controller
        super(WebSocketThread, self).__init__()
        self.parent = parent
        self.ws = websocket.WebSocket()
        self.create_connection(self.ws, self.host, self.controller)
        websocket.enableTrace(False)

    def run(self):
        self.listen(self.ws)


class _Vanta(QWidget):
    """ _Vanta is the part of the widget that processes the messages from the Websocket server.
        It creates a bunch of signals that users can register to receive
        spectrum_data       This is a json message containing just contents of the spectrum.
        hardware_status     This is the hardware status json.  Temperatures, voltages etc.
        message_data        This is all the data. Need to sort by ID to find the messages of interest.
        """

    clickedValue = pyqtSignal(int)
    spectrum_data = pyqtSignal(dict)  # emit the spectrum data
    hardware_status = pyqtSignal(dict)  # emit the hardware status data
    message_data = pyqtSignal(dict)  # emit the raw message data coming back from client.

    black_pen = QtGui.QPen()
    black_pen.setWidth(1)
    black_pen.setColor(QtGui.QColor('Black'))

    grey_pen = QtGui.QPen()
    grey_pen.setWidth(1)
    grey_pen.setColor(QtGui.QColor('lightGrey'))

    red_pen = QtGui.QPen()
    red_pen.setWidth(3)
    red_pen.setColor(QtGui.QColor('Red'))

    blue_pen = QtGui.QPen()
    blue_pen.setWidth(3)
    blue_pen.setColor(QtGui.QColor('Blue'))

    white_brush = QtGui.QBrush()
    white_brush.setColor(QtGui.QColor('white'))
    white_brush.setStyle(Qt.BrushStyle.SolidPattern)
    white_brush.isOpaque()

    black_brush = QtGui.QBrush()
    black_brush.setColor(QtGui.QColor('Black'))
    black_brush.setStyle(Qt.BrushStyle.SolidPattern)
    black_brush.isOpaque()

    blue_brush = QtGui.QBrush()
    blue_brush.setColor(QtGui.QColor('Blue'))
    blue_brush.setStyle(Qt.BrushStyle.SolidPattern)
    blue_brush.isOpaque()

    def __init__(self, host, controller):

        super(_Vanta, self).__init__(flags=Qt.WindowFlags(), parent=None)

        self.setSizePolicy(
            QSizePolicy.MinimumExpanding,
            QSizePolicy.MinimumExpanding
        )

        self.setMinimumSize(100, 100)

        self.bounds = QRect(0, 0, 100, 100)
        self.host = host
        self.port = 7860
        self.command_id = 0
        self.controller = controller

        self.message = ""
        self.bytes_received = 0
        self.message_count = 0
        self.status_message = ""
        self.xrays_on = False

        self.gpio_bank1 = 0
        self.gpio_bank2 = 0
        self.gpio_bank3 = 0
        self.gpio_bank4 = 0

        self.timer = QTimer()
        self.timer.timeout.connect(self.on_timer)
        self.timer_interval = 1000
        self.timer.start(self.timer_interval)

        self.analysis_result = ""

        """ Data for timing how long tests take."""

        self.final_result = False
        self.final_result_timestamp = datetime.datetime.utcnow()
        self.final_tick_count = 0

        self.unit_stopped = False
        self.stopped_timestamp = datetime.datetime.utcnow()
        self.stopped_tick_count = 0
        self.stopped_reason = ""

        self.unit_started = False
        self.started_timestamp = datetime.datetime.utcnow()
        self.started_tick_count = 0

        self.exposure_started_tick_count = 0
        self.final_spectrum_tick_count = 0
        self.got_final_spectrum = False
        self.last_real_time = 0

        self.test_time = 0

        self.last_result_tick_count = 0

        # Construct the URL and create the websocket thread that will handle the communications.
        url = "ws://" + self.host + ":" + str(self.port)
        # controller = False

        self.websocket_thread = WebSocketThread(self, url, controller)
        self.websocket_thread.start()

        #   One of the most important lines!  Here we connect the notification signal emitted by the websocket thread
        #   to the message_dispatcher function.
        self.websocket_thread.notification.connect(self.message_dispatcher)

    def next_command_id(self):
        """
        Generate a new command id for each command we send.  This can be used to track responses.
        If we send a command to get something, the response should return our id.
        """
        self.command_id = self.command_id + 1
        return self.command_id

    def send_basic_command(self, command_id):
        """
        Send commands that don't have parameters.
        """
        command = dict()
        command["commandId"] = command_id
        command["id"] = 0
        command["params"] = {}
        self.websocket_thread.send_command(command)

    def send_command(self, command):

        self.websocket_thread.send_command(command)

    def get_hardware_status(self):
        """
        Request the hardware status from the device.
        """
        self.send_basic_command(210)

    def _calculate_clicked_value(self, e):
        print(e)
        value = 10
        self.clickedValue.emit(value)

    def mouseMoveEvent(self, e):
        self._calculate_clicked_value(e)

    def mousePressEvent(self, e):
        self._calculate_clicked_value(e)

    def paint_warning_led(self):
        LED_RADIUS = 6
        painter = QtGui.QPainter(self)
        self.bounds = QRect(0, 0, painter.device().width(), painter.device().height())
        # Draw the x-ray light.
        if self.xrays_on:
            light_color = QtGui.QColor('red')
        else:
            light_color = QtGui.QColor('grey')

        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        brush = QtGui.QBrush()
        brush.setStyle(Qt.BrushStyle.SolidPattern)
        brush.isOpaque()
        brush.setColor(light_color)
        #   This next block would have put a white border around each sphere.
        pen = QtGui.QPen()
        pen.setWidth(1)
        pen.setColor(QtGui.QColor('white'))
        painter.setPen(pen)

        pen = QtGui.QPen()
        pen.setWidth(1)
        pen.setColor(light_color)
        painter.setPen(pen)
        painter.setBrush(brush)

        locationX = self.bounds.right() - 15
        locationY = self.bounds.top() + 15
        g = QtGui.QRadialGradient(locationX - LED_RADIUS / 1.75, locationY - LED_RADIUS / 1.75, LED_RADIUS)
        g.setColorAt(1, light_color)
        g.setColorAt(0, QtGui.QColor('white'))
        painter.setBrush(g)

        painter.drawEllipse(locationX - LED_RADIUS, locationY - LED_RADIUS, LED_RADIUS * 2,
                            LED_RADIUS * 2)
        painter.end()
        # end x-ray light

    def paint_other_chemistry(self):
        chemistry_margin = 10
        chemistry_top_margin = 50
        chemistry_bottom_margin = 90

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        self.bounds = QRect(0, 0, painter.device().width(), painter.device().height())

        chemistry_rect_width = self.bounds.right() - self.bounds.left() - (2 * chemistry_margin)
        chemistry_rect_height = self.bounds.bottom() - (chemistry_top_margin + chemistry_bottom_margin)
        if chemistry_rect_height < 0:
            chemistry_rect_height = 0
        chemistry_rect = QRect(self.bounds.left() + chemistry_margin,
                               self.bounds.top() + chemistry_top_margin,
                               chemistry_rect_width,
                               chemistry_rect_height)
        painter.setClipRect(chemistry_rect)
        # Scale the font size to the window dimensions
        if chemistry_rect_height / chemistry_rect_width > 2:
            font_size = int(chemistry_rect_height / 30)
        else:
            font_size = int(chemistry_rect_height / 20)
        if font_size < 8:
            font_size = 8

        # Set the font for drawing the results and retrieve the size used, in case it is not the one we asked for.

        normal_font = QtGui.QFont()
        normal_font.setStyleHint(QtGui.QFont.TypeWriter)
        normal_font = QtGui.QFont("Courier", font_size)
#        font_size = normal_font.pointSize()

        painter.setFont(normal_font)
        info = painter.fontInfo()
        font_size = info.pointSize()

        small_font = QtGui.QFont()
        small_font.setStyleHint(QtGui.QFont.TypeWriter)
        # small_font = QtGui.QFont("Courier", int(font_size / 2))

        # Fill the area in white.
        painter.fillRect(chemistry_rect, self.white_brush)
        painter.setPen(self.black_pen)

        method_name = self.analysis_result['params']['result']['analysis']['methodDispName']

        text_str = "Method: \"" + method_name + "\""
        painter.drawText(chemistry_rect.left() + chemistry_margin, chemistry_rect.top() + font_size * 2, text_str)

        row = 0
        rowOffset = int(font_size * 5)
        rowH = int(font_size + 30)

        text_str = str.format("{0:<2}    {1:6}{2:6}", "El", "Conc.", "Err")
        painter.drawText(chemistry_rect.left() + chemistry_margin, chemistry_rect.top() + rowOffset + (row * rowH),
                         text_str)
        row = row + 1

        results_list = []
        for display_element in self.analysis_result['params']['result']['elementList']:
            for element in self.analysis_result['params']['result']['chemistry']:
                if element['elementName'] == display_element:
                    concentration = element['concentration']
                    error = element['error']
                    tup = (display_element, concentration, error)
                    results_list.append(tup)

        results_list.sort(key=lambda a: a[1], reverse=True)  # Sort the list by concentration largest to smallest

        for display_element, concentration, error in results_list:
            # start_pixel = font_size * 20  # Inset the bar 20 characters from the edge.
            # right_margin = 20
            top_bottom_margin = 20
            painter.setPen(self.grey_pen)
            painter.setBrush(self.white_brush)
            painter.setFont(normal_font)
            frame_rect = QRect(chemistry_rect.left(),  # left
                               chemistry_rect.top() + top_bottom_margin + rowOffset + (
                                       (row - 1) * rowH),  # top
                               chemistry_rect_width,  # width
                               rowH)
            painter.drawRect(frame_rect)

            painter.setPen(self.black_pen)
            painter.setBrush(self.black_brush)
            text_str = str.format("{0:<2}  {1:6.3f}{2:6.3f}", display_element, concentration, 3 * error)
            painter.drawText(chemistry_rect.left() + chemistry_margin,
                             chemistry_rect.top() + rowOffset + (row * rowH), text_str)
            row = row + 1

    def paint_alloy_chemistry(self):
        chemistry_margin = 10
        chemistry_top_margin = 50
        chemistry_bottom_margin = 90
        # font_size = 10

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        self.bounds = QRect(0, 0, painter.device().width(), painter.device().height())

        chemistry_rect_width = self.bounds.right() - self.bounds.left() - (2 * chemistry_margin)
        chemistry_rect_height = self.bounds.bottom() - (chemistry_top_margin + chemistry_bottom_margin)
        if chemistry_rect_height < 0:
            chemistry_rect_height = 0
        chemistry_rect = QRect(self.bounds.left() + chemistry_margin,
                               self.bounds.top() + chemistry_top_margin,
                               chemistry_rect_width,
                               chemistry_rect_height)
        painter.setClipRect(chemistry_rect)
        # Scale the font size to the window dimensions
        font_size = int(chemistry_rect_height / 20)
        if font_size < 8:
            font_size = 8

        # Set the font for drawing the results and retrieve the size used, in case it is not the one we asked for.
        normal_font = QtGui.QFont()
        normal_font.setStyleHint(QtGui.QFont.TypeWriter)
        normal_font = QtGui.QFont("Courier", font_size)
        # font_size = normal_font.pointSize()

        painter.setFont(normal_font)
        # info = painter.fontInfo()
        # font_size = info.pointSize()

        small_font = QtGui.QFont()
        small_font.setStyleHint(QtGui.QFont.TypeWriter)
        small_font = QtGui.QFont("Courier", int(font_size / 2))

        # Fill the area in white.
        painter.fillRect(chemistry_rect, self.white_brush)
        painter.setPen(self.black_pen)
        text_str = ""
        if len(self.analysis_result):

            # Find the grade we are trying to compare the chemistry to.  We do this by looking for the grade that has
            # a non-zero value in compGrade.
            comp_grade = None
            for g in self.analysis_result['params']['result']['gradeMatch']:
                if g['compGrade'] > 0:
                    comp_grade = g
                    break

            method_name = self.analysis_result['params']['result']['analysis']['methodDispName']
            grade_count = len(self.analysis_result['params']['result']['gradeMatch'])
            # Print the grade name
            if grade_count:
                try:
                    text_str = "Method: \"" + method_name + "\". Grades: "
                    for g in self.analysis_result['params']['result']['gradeMatch']:
                        text_str = text_str + str(g['gradeName']) + " "
                except KeyError:
                    pass
                painter.drawText(chemistry_rect.left() + chemistry_margin, chemistry_rect.top() + font_size * 2,
                                 text_str)

            row = 0
            rowOffset = int(font_size * 5)
            rowH = int(font_size + 30)

            text_str = str.format("{0:<2}    {1:6}{2:6}", "El", "Conc", "Err")
            painter.drawText(chemistry_rect.left() + chemistry_margin,
                             chemistry_rect.top() + rowOffset + (row * rowH), text_str)
            row = row + 1

            results_list = []  # Empty list to contain all the elements.
            if comp_grade:

                # Add all the nominal chemistry to the list
                for gradeSpec in comp_grade['gradeSpec']:
                    if gradeSpec['matchResult'] == "Nominal":
                        value_min = float(gradeSpec['minVal'])
                        value_max = float(gradeSpec['maxVal'])
                        value_range = value_max - value_min
                        match_result = gradeSpec['matchResult']

                        concentration = value_min + (value_range / 2.0)
                        error = 0
                        tup = (gradeSpec['elementName'], concentration, error, value_min, value_max,
                               value_range, match_result)
                        results_list.append(tup)

                n_sigma = comp_grade['matchNSigma']
                for element in self.analysis_result['params']['result']['chemistry']:
                    if element['concentration'] > 0:  # we need to show this element
                        value_min = 0
                        value_max = 0
                        value_range = value_max - value_min
                        match_result = ""

                        for gradeSpec in comp_grade['gradeSpec']:
                            if element['elementName'] == gradeSpec['elementName']:
                                value_min = float(gradeSpec['minVal'])
                                value_max = float(gradeSpec['maxVal'])
                                value_range = value_max - value_min
                                match_result = gradeSpec['matchResult']

                        concentration = element['concentration']
                        error = element['error']
                        tup = (element['elementName'], concentration, error, value_min, value_max,
                               value_range, match_result)
                        results_list.append(tup)

                results_list.sort(key=lambda a: a[1],
                                  reverse=True)  # Sort the list by concentration largest to smallest

                start_pixel = font_size * 20  # Inset the bar 20 characters from the edge.
                right_margin = 20
                top_bottom_margin = 20

                for grade_element, concentration, error, value_min, value_max, value_range, match_result\
                        in results_list:

                    painter.setPen(self.grey_pen)
                    painter.setBrush(self.white_brush)
                    painter.setFont(normal_font)
                    frame_rect = QRect(chemistry_rect.left(),  # left
                                       chemistry_rect.top() + top_bottom_margin + rowOffset + (
                                               (row - 1) * rowH),  # top
                                       chemistry_rect_width,  # width
                                       rowH)
                    painter.drawRect(frame_rect)

                    element_symbol_rect = frame_rect
                    element_symbol_rect.setWidth(font_size * 4)  # Reduce Width
                    element_symbol_rect.setHeight(rowH - 10)

                    if match_result == "TooLow":
                        painter.setPen(self.blue_pen)
                        painter.drawRoundedRect(element_symbol_rect, 10, 10)
                        pass
                    if match_result == "TooHigh" or match_result == "NoSpec":
                        painter.setPen(self.red_pen)
                        painter.drawRoundedRect(element_symbol_rect, 10, 10)
                        pass

                    painter.setPen(self.black_pen)
                    painter.setBrush(self.black_brush)
                    text_str = str.format("{0:<2}  {1:6.3f}{2:6.3f}", grade_element, concentration, 3 * error)
                    painter.drawText(chemistry_rect.left() + chemistry_margin,
                                     chemistry_rect.top() + rowOffset + (row * rowH), text_str)

                    # calculate and draw the bar.
                    if match_result == "Tramp":
                        text_str = str.format("{0:<2} <{1:6.2f}%", "Resid.", value_max)
                        painter.setPen(self.blue_pen)
                        painter.drawText(chemistry_rect.left() + int(chemistry_rect_width / 2),
                                         chemistry_rect.top() + rowOffset + (row * rowH), text_str)
                        pass
                    elif match_result == "NoSpec":
                        text_str = str.format("{0:<2} ", "NoSpec.")
                        painter.setPen(self.red_pen)
                        painter.drawText(chemistry_rect.left() + int(chemistry_rect_width / 2),
                                         chemistry_rect.top() + rowOffset + (row * rowH), text_str)
                        pass
                    elif match_result == "Nominal":
                        text_str = str.format("{0:<2} {1:4.2f} - {2:4.2f}%", "Nom.", float(value_min), float(value_max))
                        painter.setPen(self.blue_pen)
                        painter.drawText(chemistry_rect.left() + int(chemistry_rect_width / 2),
                                         chemistry_rect.top() + rowOffset + (row * rowH), text_str)
                        pass
                    elif match_result == "":
                        text_str = str.format("{0:<2} ", "")
                        painter.drawText(chemistry_rect.left() + int(chemistry_rect_width / 2),
                                         chemistry_rect.top() + rowOffset + (row * rowH), text_str)
                        pass
                    else:
                        painter.setPen(self.black_pen)
                        painter.setBrush(self.black_brush)
                        bar_width = chemistry_rect_width - (start_pixel + right_margin)
                        element_rect = QRect(chemistry_rect.right() - chemistry_rect_width + start_pixel,  # left
                                             chemistry_rect.top() + top_bottom_margin + rowOffset + ((row - 1) * rowH),
                                             # top
                                             bar_width,  # width
                                             rowH - top_bottom_margin)  # height

                        # Fill the whole bar in green
                        g = QtGui.QLinearGradient(element_rect.topLeft(), element_rect.bottomLeft())
                        g.setColorAt(1, QtGui.QColor('Green'))
                        g.setColorAt(0, QtGui.QColor('white'))
                        # painter.setBrush(g)
                        painter.fillRect(element_rect, g)

                        # Calculate the full range of concentration that the bar represents.
                        bar_min = value_min - n_sigma * error
                        if bar_min < 0:
                            bar_min = 0

                        bar_max = value_max + n_sigma * error
                        if bar_min > 100:
                            bar_min = 100

                        bar_range = bar_max - bar_min

                        if bar_min > 0:
                            bar_min = bar_min - bar_range / 10.0

                        if bar_max < 100:
                            bar_max = bar_max + bar_range / 10.0

                        bar_range = bar_max - bar_min

                        # Calculate the position to draw the current chemistry on that bar
                        position_conc = int((concentration - bar_min) * bar_width / bar_range)
                        marker_rect = QRect(element_rect.left() + position_conc, element_rect.top(), 1,
                                            rowH - top_bottom_margin)
                        painter.fillRect(marker_rect, self.blue_brush)

                        # Calculate and place the numbers for the ranges.
                        position_min = int((value_min - bar_min) * bar_width / bar_range)
                        marker_rect = QRect(element_rect.left() + position_min, element_rect.top(), 1, rowH)
                        # painter.fillRect(marker_rect, self.black_brush)
                        text_str = str.format("{:3.2f}", value_min)
                        painter.setFont(small_font)
                        painter.drawText(marker_rect.left() - font_size, marker_rect.bottom() - 5, text_str)

                        position_max = int((value_max - bar_min) * bar_width / bar_range)
                        marker_rect = QRect(element_rect.left() + position_max, element_rect.top(), 1, rowH)
                        # painter.fillRect(marker_rect, self.black_brush)
                        text_str = str.format("{:3.2f}", value_max)
                        painter.drawText(marker_rect.left() - font_size, marker_rect.bottom() - 5, text_str)

                        red_pixels_left = int(bar_width / 10)
                        red_pixels_right = int(bar_width / 10)

                        if bar_min <= 0:
                            red_pixels_left = 0
                        if bar_max >= 100:
                            red_pixels_right = 0

                        # draw the yellow parts.
                        min_yellow_width = 1
                        error_pixels_left = red_pixels_left + int(
                            ((n_sigma * error) / bar_range) * bar_width) + min_yellow_width
                        error_pixels_right = red_pixels_right + int(
                            ((n_sigma * error) / bar_range) * bar_width) + min_yellow_width

                        if bar_min <= 0:
                            error_pixels_left = 0
                        if bar_max >= 100:
                            error_pixels_right = 0

                        error_rect_left = QRect(element_rect.left(), element_rect.top(), error_pixels_left,
                                                rowH - top_bottom_margin)
                        error_rect_right = QRect(element_rect.right() - error_pixels_right, element_rect.top(),
                                                 error_pixels_right,
                                                 rowH - top_bottom_margin)

                        g = QtGui.QLinearGradient(element_rect.topLeft(),
                                                  element_rect.bottomLeft())
                        g.setColorAt(1, QtGui.QColor('Yellow'))
                        g.setColorAt(0, QtGui.QColor('white'))
                        painter.setBrush(g)
                        #   brush.setColor(QtGui.QColor('Yellow'))
                        #   painter.setBrush(brush)
                        painter.fillRect(error_rect_left, g)
                        painter.fillRect(error_rect_right, g)

                        # draw the red parts.
                        red_rect_left = QRect(element_rect.left(), element_rect.top(), red_pixels_left,
                                              rowH - top_bottom_margin)
                        red_rect_right = QRect(element_rect.right() - red_pixels_right, element_rect.top(),
                                               red_pixels_right, rowH - top_bottom_margin)

                        g = QtGui.QLinearGradient(element_rect.topLeft(),
                                                  element_rect.bottomLeft())
                        g.setColorAt(1, QtGui.QColor('Red'))
                        g.setColorAt(0, QtGui.QColor('white'))
                        painter.setBrush(g)
                        painter.fillRect(red_rect_left, g)
                        painter.fillRect(red_rect_right, g)

                    row = row + 1

    def paint_chemistry(self):
        if len(self.analysis_result):
            # We have a result so let's decide how to display it.
            if len(self.analysis_result['params']['result']['gradeMatch']):
                self.paint_alloy_chemistry()
            else:
                self.paint_other_chemistry()

    def paint_messages(self):
        painter = QtGui.QPainter(self)
        self.bounds = QRect(0, 0, painter.device().width(), painter.device().height())

        # Fill the area in black.
        brush = QtGui.QBrush()
        brush.setColor(QtGui.QColor('black'))
        brush.setStyle(Qt.BrushStyle.SolidPattern)
        brush.isOpaque()
        painter.fillRect(self.bounds, brush)

        # Outline in white.
        pen = QtGui.QPen()
        pen.setWidth(1)
        pen.setColor(QtGui.QColor('yellow'))
        painter.setPen(pen)
        painter.setBrush(brush)
        painter.drawRect(self.bounds)

        painter.setFont(QtGui.QFont("Arial", 8))

        painter.setPen(QtGui.QColor('White'))
        text_str = "Host: " + str(self.host)
        painter.drawText(self.bounds.left() + 5, self.bounds.top() + 15, text_str)

        text_str = "Last message: " + str(self.message)
        painter.drawText(self.bounds.left() + 5, self.bounds.bottom() - 60, text_str)

        text_str = "Bytes: " + str(self.bytes_received)
        painter.drawText(self.bounds.left() + 5, self.bounds.bottom() - 40, text_str)

        text_str = "Messages: " + str(self.message_count)
        painter.drawText(self.bounds.left() + 5, self.bounds.bottom() - 20, text_str)

        text_str = "Status: " + str(self.status_message)
        painter.drawText(self.bounds.left() + 5, self.bounds.bottom() - 5, text_str)
        painter.end()

    def paint_gpio_state(self):
        painter = QtGui.QPainter(self)
        self.bounds = QRect(0, 0, painter.device().width(), painter.device().height())
        brush = QtGui.QBrush()
        gpio_rect = QRect(self.bounds.left() + 150, self.bounds.top() + 5, 130, 36)
        brush.setColor(QtGui.QColor('darkGreen'))
        brush.setStyle(Qt.BrushStyle.SolidPattern)
        brush.isOpaque()
        painter.fillRect(gpio_rect, brush)

        light_color = QtGui.QColor('grey')
        pen = QtGui.QPen()
        pen.setWidth(1)
        pen.setColor(light_color)
        painter.setPen(pen)
        painter.setBrush(brush)
        radius = 5

        for bit in range(0, 8):
            if self.gpio_bank3 & 1 << bit:
                light_color = QtGui.QColor('red')
            else:
                light_color = QtGui.QColor('darkGray')
            locationX = gpio_rect.left() + 10 + (15 * bit)
            locationY = gpio_rect.top() + 10
            g = QtGui.QRadialGradient(locationX - radius / 1.75, locationY - radius / 1.75, radius)
            g.setColorAt(1, light_color)
            g.setColorAt(0, QtGui.QColor('white'))
            painter.setBrush(g)
            painter.drawEllipse(locationX - radius, locationY - radius, radius * 2, radius * 2)

        for bit in range(0, 8):
            if self.gpio_bank4 & 1 << bit:
                light_color = QtGui.QColor('red')
            else:
                light_color = QtGui.QColor('darkGray')
            locationX = gpio_rect.left() + 10 + (15 * bit)
            locationY = gpio_rect.top() + 25
            g = QtGui.QRadialGradient(locationX - radius / 1.75, locationY - radius / 1.75, radius)
            g.setColorAt(1, light_color)
            g.setColorAt(0, QtGui.QColor('white'))
            painter.setBrush(g)
            painter.drawEllipse(locationX - radius, locationY - radius, radius * 2, radius * 2)

        painter.end()

    def paintEvent(self, e):
        self.paint_messages()
        self.paint_warning_led()
        self.paint_gpio_state()
        self.paint_chemistry()

    def on_timer(self):
        if self.controller:
            self.send_basic_command(244)

        self.get_hardware_status()
        self.update()

    def message_dispatcher(self, data):
        """ This function is where all the magic happens. Here is where the data comes to be processed from the
            websocket. Every packet of data starts with a commandId which tells us the type of data.
            Here we make a basic separation between notifications and responses.

            A response comes after a request for information or in response to an action.
            For example if we send the start command (commandId = 601) we will get a start response of commandId==601

            A notification comes at random times and generally are status updates, or progress during a test.
            All notifications share the same commandId==403.  They use the "id" field to tell the type of information.
            For example "id" == 100:  is a status notification.
        """

        message_bytes = len(str(data))

        self.bytes_received = self.bytes_received + message_bytes
        self.message_count = self.message_count + 1

        self.message = str(data["commandId"]) + "," + str(data["id"])

        if data["commandId"] == 403:
            self.notification_handler(data)
        else:
            self.response_handler(data)

        # Send the data to any clients
        self.message_data.emit(data)

    def notification_handler(self, data):  # messages with commandId of 403
        # ------------------------------------
        if data["id"] == 100:
            # print("status", data)
            message = data["params"]["info"] + " " + data["params"]["systemStatus"]
            self.on_status_message_update(message)
            return

        # ------------------------------------
        if data["id"] == 132:
            self.hardware_status.emit(data)
            return

        # ------------------------------------
        if data["id"] == 200:   # Test started
            self.unit_stopped = False
            self.unit_started = True
            self.final_result = False
            self.started_timestamp = datetime.datetime.utcnow()
            try:
                self.started_tick_count = data['tickCount']
                self.got_final_spectrum = False
                self.last_real_time = 0
            except KeyError:
                self.started_tick_count = -1

        # ------------------------------------
        if data["id"] == 201:
            self.unit_stopped = True
            self.unit_started = False
            self.stopped_timestamp = datetime.datetime.utcnow()
            try:
                self.stopped_tick_count = data['tickCount']
                self.stopped_reason = data['params']['stopReason']
            except KeyError:
                self.stopped_tick_count = -1

        # ------------------------------------
        if data["id"] == 202:

            try:
                self.exposure_started_tick_count = data['tickCount']
            except KeyError:
                self.exposure_started_tick_count = -1

            # print("Exposure started in {} s".format((self.exposure_started_tick_count-self.started_tick_count )/1e3))

        # ------------------------------------
        if data["id"] == 204:
            spectrum = data['params']['spectrum']
            if spectrum['isFinal']:
                print("!")
            self.spectrum_data.emit(spectrum)
            real_time =spectrum['realTime']
            self.last_real_time = real_time;
            if real_time == self.test_time:
                self.final_spectrum_tick_count = data['tickCount']
                self.got_final_spectrum = True
            return

        # ------------------------------------
        if data["id"] == 206:
            cur_tick_count = data['tickCount']
            # print("Time since last result = {}s ".format((cur_tick_count-self.last_result_tick_count)/1e3))
            self.last_result_tick_count = cur_tick_count

            if data['params']['result']['analysis']['final']:  # and it is the final result.

                spectra = data['params']['result']['spectra']
                if len(spectra):
                    real_time = float(data['params']['result']['spectra'][0]['realTime'])
                else:
                    real_time = 0.0
                message = datetime.datetime.now().isoformat() + str(
                    "_Vanta Unit {} Got a final result. Realtime = {:.3f}s".format(self.host, real_time))
                self.final_result = True
                self.final_result_timestamp = datetime.datetime.utcnow()
                try:
                    self.final_tick_count = data['tickCount']
                except KeyError:
                    self.final_tick_count = -1
                if self.got_final_spectrum:
                    message = message + str(" Time since last spectrum ={}s"
                                            .format((self.final_tick_count-self.final_spectrum_tick_count)/1e3))
                else:
                    message = message + str(" Did not receive the final spectrum before final result!") + \
                              str("Last real time was {:.3f} s").format(self.last_real_time) + \
                              str("Stopped reason = ")+self.stopped_reason
                print(message)
            self.on_analysis_result(data)
            return

        # ------------------------------------
        if data["id"] == 139:
            # print("GPIOs changed", data)
            self.on_gpios_changed(data)
            return

        # ------------------------------------
        if data["id"] == 301:
            # print("Method loaded", data)
            self.send_basic_command(771)
            return

        # ------------------------------------
        if data["id"] == 501:
            message = "Factory Status: " + data["params"]["status"]
            self.on_status_message_update(message)
            return

        # ------------------------------------
        if data["id"] == 502:
            message = "Factory Progress: " + str(data["params"]["progress"])
            self.on_status_message_update(message)
            return

        # ------------------------------------
        if data["id"] == 513:
            spectrum_data = data['params']['spectrum']
            spectrum = {
                            'data': spectrum_data,
                            'energyOffset': 0,
                            'energySlope': 20,
                            'liveTime': data['params']['liveTimeFromHardware'],
                            'exposureNumber': data['params']['exposureType']
                        }
            self.spectrum_data.emit(spectrum)
        # ------------------------------------

    def response_handler(self, data):
        if data["commandId"] == 771:
            self.test_time = data['params']['beams'][0]['max']


    def on_analysis_result(self, data):
        self.analysis_result = data
        self.paint_chemistry()

    def on_gpios_changed(self, data):
        self.gpio_bank1 = data['params']['bank1']
        self.gpio_bank2 = data['params']['bank2']
        self.gpio_bank3 = data['params']['bank3']
        self.gpio_bank4 = data['params']['bank4']
        self.paintEvent(self)

    def on_status_message_update(self, message):
        self.status_message = message
        if "X-rays on" in message:
            self.xrays_on = True
        if "X-rays off" in message:
            self.xrays_on = False
        self.update()


class VantaWidget(QWidget):
    widget_message_data = pyqtSignal(dict)  # emit the raw message data coming back from client.
    widget_spectrum_data = pyqtSignal(dict)  # emit the raw spectrum data coming back from client.

    def __init__(self, host="127.0.0.1", controller=False, method="", name="", *args, **kwargs):

        super(VantaWidget, self).__init__(*args, **kwargs)
        self.setSizePolicy(
            QSizePolicy.MinimumExpanding,
            QSizePolicy.MinimumExpanding
        )

        self.vanta_id = uuid.uuid4()
        self.setMinimumSize(250, 150)
        self.method = method
        self.name = name
        main_layout = QVBoxLayout()
        layout = QSplitter()
        layout.setOrientation(Qt.Vertical)
        self.spectrum_view = pg.GraphicsLayoutWidget()

        self.x1 = []
        self.y1 = []

        self.spectrum_plot = self.spectrum_view.addPlot(title="",
                                                        pen=(0, 255, 255),
                                                        fontSize=4,
                                                        name="spectrum",
                                                        labels={'left': 'Counts', 'bottom': 'Energy (keV)'},
                                                        setGrid=128
                                                        )
        self.spectrum_plot.showGrid(x=True, y=True)
        self.spectrum_initialized = False
        # layout.addWidget(self.spectrum_view, alignment=Qt.Alignment())
        layout.addWidget(self.spectrum_view)
        self._vanta = _Vanta(host, controller)
        # layout.addWidget(self._vanta, alignment=Qt.Alignment())
        layout.addWidget(self._vanta)
        main_layout.addWidget(layout, alignment=Qt.Alignment())
        self.setLayout(main_layout)

        self._vanta.spectrum_data.connect(self.on_spectrum_data)
        self._vanta.message_data.connect(self.on_message_data)

    def send_basic_command(self, command):
        # print(datetime.datetime.now().isoformat()+" Sent command {} to host:{}".format(command, self._vanta.host))
        self._vanta.send_basic_command(command)

    def send_command(self, command):
        # print(datetime.datetime.now().isoformat()+" Sent command {} to host:{}".format(command, self._vanta.host))
        self._vanta.send_command(command)

    def on_message_data(self, data):
        data['vanta_id'] = self.vanta_id  # Add the UUID to the data so the handler can sort by specific unit.

        #if data["id"] == 206:
            #if self._vanta.final_result:
                #message = datetime.datetime.now().isoformat() + str(" Unit {} Got a final result".format(self.name))
                #print(message)

        self.widget_message_data.emit(data)

    def display_stability_spectrum(self, data):
        """Special case where the gain and offset are unknown, so we hard code them."""
        if self.show_spectrum:

            spectrum_data = data['params']['spectrum']
            slope = 20
            offset = 0
            #   Make the energy scale from the slope and offset data.
            self.x1 = offset + slope * np.arange(2048)
            self.y1 = spectrum_data
            label = "Stability" + str(data['params']['iteration'])
            if self.spectrum_initialized:
                self.plot.setData(self.x1, self.y1)
            else:
                self.spectrum_plot = self.spectrum_plot.plot(self.x1, self.y1, pen=(0, 255, 255),
                                                             name=label, clear="True")
                self.spectrum_initialized = True

    def on_spectrum_data(self, spectrum_data):
        spectrum_data['vanta_id'] = self.vanta_id
        self.widget_spectrum_data.emit(spectrum_data)
        # print("spectrum_data")
        slope = spectrum_data['energySlope']
        offset = spectrum_data['energyOffset']

        # Make the energy scale from the slope and offset data.
        x1 = offset + slope * np.arange(2048)
        y1 = spectrum_data['data']
        label = "Beam-" + str(spectrum_data['exposureNumber'])
        if self.spectrum_initialized:
            self.spectrum_plot.setData(x1, y1)
        else:
            self.spectrum_plot = self.spectrum_plot.plot(x1, y1, pen=(0, 255, 255), name=label, clear="True")
            self.spectrum_initialized = True

    @property
    def vanta(self):
        return self._vanta
