# Python 3.11 #
import sys
import time
import os

from datetime import datetime
import re  # Regular expression parser. Used to clean up the logs from the hardware.

# Need to have PyQT5 installed for the GUI widgets.  pip install PyQT5
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5.QtGui import *

import numpy as np  # numpy package is used for some array manipulation.  pip install numpy

import pyqtgraph as pg  # pyqtgraph is used to display the spectrum data pip install pyqtgraph
import websocket  # websocket is used for communicating with the device over the network.  pip install websocket-client
import json
import tempfile


def save_json(filename, path, foldername, data, fmt=False):
    file_name = filename

    if len(path) > 0:
        try:
            os.stat(path)
        except:
            os.mkdir(path)
        full_path = os.path.join(path, foldername)
    else:
        full_path = os.path.join(tempfile.gettempdir(), foldername)
    try:
        result = os.stat(full_path)
    except:
        result = os.mkdir(full_path)
    full_path = os.path.join(full_path, file_name)
    with open(full_path, 'w') as file:  # dump the data into a file for future access.
        if fmt:
            json.dump(data, file, indent=1, sort_keys=False)
        else:
            json.dump(data, file, indent=0, sort_keys=False)


class WebSocketThread(QThread):
    """ WebSocketThread creates the websocket connection  and then listens for the messages coming through.
        If we get data we send it using the notification signal. """

    verbose = False     # Set to true if you want to see what is going on.
    notification = pyqtSignal(dict)

    def send_command(self, command):
        """This function actually dispatches the json command to the host."""
        if self.ws.connected:
            command["id"] = self.parent.next_command_id()       # Tag each command with a new ID.
            if self.verbose:
                print("Sending ", json.dumps(command))
            result = self.ws.send_binary(json.dumps(command))   # IMPORTANT that the data is sent as BINARY not text.
            if self.verbose:
                print(result)

            time.sleep(0.05)
        else:
            if self.verbose:
                print("Cannot send command. Disconnected!")

    def create_connection(self,discovery_web_socket, web_socket, host, controller,exit_headless = False):
        """ connect to the supplied host using the supplied websocket. If we want to listen controller = false"""
        try:
            print("Discovering {}".format(host))
            discovery_web_socket.connect(host)
        except:
            print("Unable to connect")
            return False
        print("Connected=", discovery_web_socket.connected)

        if discovery_web_socket.connected: # Request the device info to see if we can connect or not and if the unit is headless.
            command = "Request device info"
            result = discovery_web_socket.send(command)  # IMPORTANT that the data here is sent as TEXT. (See send_command)
            print("Sent ", command, "Result=", result)
            result = discovery_web_socket.recv()
            print("Response=", result)
            try: # to load the discovery packet.
                data = json.loads(result)
                if data['status'] == "HEADLESS":
                    print("Device is in headless mode")
                    self.is_headless = True
                    if exit_headless:
                        command = "Exit Headless Mode"
                        result = discovery_web_socket.send(command)  # IMPORTANT that the data here is sent as TEXT. (See send_command)
                        print("Sent ", command, "Result=", result)
                        result = discovery_web_socket.recv()
                        print("Response=", result)
            except:
                pass


        try:
            print("Connecting to {}".format(host))
            web_socket.connect(host)
        except:
            print("Unable to connect")
            return False
        print("Connected=", web_socket.connected)

        if web_socket.connected and controller:             # connect as a controller
            command = "Hi i am a controller"
            result = web_socket.send(command)        # IMPORTANT that the data here is sent as TEXT. (See send_command)
            print("Sent ", command, "Result=", result)

            result = web_socket.recv()
            print("Response=", result)
            if result == "Server ready to receive commands.":
                return True
            else:
                return False
        else:                                       # connect as a listener

            command = "Hi i am a listener"
            result = web_socket.send(command)         # IMPORTANT that the data here is sent as TEXT.(See send_command)
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
                        print(result,)
                    data = json.loads(result)
                    self.notification.emit(data)
                except:
                    print(".")
                time.sleep(0.01)
            else:
                time.sleep(1)
                self.create_connection(self.ws, self.host, self.controller)

    def __init__(self, parent, host, controller,exit_headless):
        self.host = host
        self.controller = controller
        self.exit_headless = exit_headless
        self.is_headless = False

        super(WebSocketThread, self).__init__()
        self.parent = parent
        self.ws = websocket.WebSocket()
        self.discovery_ws = websocket.WebSocket()
        self.create_connection(self.discovery_ws,self.ws, self.host, self.controller, self.exit_headless)
        websocket.enableTrace(False)

    def run(self):
        self.listen(self.ws)


class TestTimeDialog(QDialog):
    def __init__(self, parent=None, params=None):
        super().__init__(parent=parent)
        self.beam_settings = params
        self.setWindowTitle("Configure Test Times")



        QBtn = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        self.buttonBox = QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        self.beam1_time_max = self.beam_settings['beams'][0]['max']
        self.beam1_time_min = self.beam_settings['beams'][0]['min']
        beam_count = len(self.beam_settings['beams'])
        if beam_count > 1:
            self.beam2_time_max = self.beam_settings['beams'][1]['max']
            self.beam2_time_min = self.beam_settings['beams'][1]['min']
        else:
            self.beam2_time_max = 0
            self.beam2_time_min = 0


        self.timeBox1 = QSpinBox()
        self.timeBox1.setPrefix("Beam 1 time ")
        self.timeBox1.setSuffix(" (s)")
        self.timeBox1.setValue(self.beam1_time_max)
        self.timeBox1.setMinimum(self.beam1_time_min)
        self.timeBox1.setMaximum(300)
        self.timeBox1.setFixedWidth(160)

        self.timeBox2 = QSpinBox()
        self.timeBox2.setPrefix("Beam 2 time ")
        self.timeBox2.setSuffix(" (s)")
        self.timeBox2.setValue(self.beam2_time_max)
        self.timeBox2.setMinimum(self.beam2_time_min)
        self.timeBox2.setMaximum(300)
        self.timeBox2.setFixedWidth(160)

        self.beams_table = QTableWidget(0, 3)
        self.beams_table.setMinimumWidth(320)
        self.beams_table.setMaximumWidth(320)
        self.beams_table.setMinimumHeight(60)
        self.beams_table.setMaximumHeight(120)
        self.beams_table.setHorizontalHeaderLabels(['Beam', 'Min', 'Max'])
        self.beams_table.setColumnWidth(0, 100)  # Beam
        self.beams_table.setColumnWidth(1, 100)  # Min
        self.beams_table.setColumnWidth(2, 100)  # Max

        row = 0
        for b in self.beam_settings['beams']:
            self.beams_table.insertRow(row)
            self.beams_table.setRowHeight(0, 20)
            beam = QTableWidgetItem(str(b['beam']))
            beam.setTextAlignment(Qt.AlignHCenter + Qt.AlignVCenter)
            self.beams_table.setItem(row, 0, beam)

            min = QTableWidgetItem(str(b['min']))
            beam.setTextAlignment(Qt.AlignHCenter + Qt.AlignVCenter)
            self.beams_table.setItem(row, 1, min)

            max = QTableWidgetItem(str(b['max']))
            beam.setTextAlignment(Qt.AlignHCenter + Qt.AlignVCenter)
            self.beams_table.setItem(row, 2, max)

            row = row+1

        self.single_beam = QRadioButton('Single beam - no LE')
        if self.beam_settings['alloyPlusOptions']['singleBeamNoLE'] is True:
            self.single_beam.setChecked(True)

        self.single_beam_LE = QRadioButton('Single beam - with LE')
        if self.beam_settings['alloyPlusOptions']['singleBeamWithLE'] is True:
            self.single_beam_LE.setChecked(True)
        self.two_beams = QRadioButton('Two beams always')
        if self.beam_settings['alloyPlusOptions']['twoBeamsAlways'] is True:
            self.two_beams.setChecked(True)
        self.smart_sort = QRadioButton('SmartSort')
        if self.beam_settings['alloyPlusOptions']['smartSort'] is True:
            self.smart_sort.setChecked(True)

        radio_layout = QVBoxLayout()

        radio_layout.addWidget(self.single_beam)
        radio_layout.addWidget(self.single_beam_LE)
        radio_layout.addWidget(self.two_beams)
        radio_layout.addWidget(self.smart_sort)

        self.layout = QVBoxLayout()
#        message = QLabel("Enter the test times")
#        self.layout.addWidget(message)
        self.layout.addWidget(self.beams_table)
       # self.layout.addWidget(self.timeBox1)
       # self.layout.addWidget(self.timeBox2)

        self.layout.addLayout(radio_layout)

        self.layout.addWidget(self.buttonBox)
        self.setLayout(self.layout)


    def accept(self):
            print("OK pressed?")
            self.beam_settings['beams'][0]['max'] = int(self.beams_table.item(0, 2).text())
            try:
                self.beam_settings['beams'][1]['max'] = int(self.beams_table.item(1, 2).text())
            except Exception as e:
                print(repr(e))
            try:
                self.beam_settings['beams'][2]['max'] = int(self.beams_table.item(2, 2).text())
            except Exception as e:
                print(repr(e))

            self.beam_settings['alloyPlusOptions']['singleBeamNoLE'] = self.single_beam.isChecked()
            self.beam_settings['alloyPlusOptions']['singleBeamWithLE'] = self.single_beam_LE.isChecked()
            self.beam_settings['alloyPlusOptions']['twoBeamsAlways'] = self.two_beams.isChecked()
            self.beam_settings['alloyPlusOptions']['smartSort'] = self.smart_sort.isChecked()

            super().accept()


class AppForm(QMainWindow):

    host = ""
    port = ""

    logged_in = False
    test_running = False
    initiated = False
    repeat_tests = False
    command_id = 0
    last_log = ''

    def __init__(self, parent=None):
        #   Start by opening the json configuration file and finding out the connection type and the host name
        #   There is a "special case" for Vanta pXRF which can be connected via USB.  We handle that by hard-coding the
        #   address to be 192.168.7.2.  See below.
        #
        #   {
        # 	    "connection" : "Network",       Type if connection.  Either 'Network' or 'USB'
        # 	    "host" : "Vanta-900005",        Unit to connect to.  Can be domain name or IP address.
        # 	    "port" : "7860",                Do not change this.
        # 	    "controller" : false,           Set to true if you want to start tests, change modes etc.
        # 	                                    Can only ever be one controller at a time.
        #                                       Set controller to false if you just want to listen to the data.
        #       "watchdog"	: true              This should be true.  Any controller that does not pet the dog will
        #                                       cause the tests to potentially stop early.
        #   }
        #
        #   examples of valid host names
        #   host = "192.168.7.2"                Local device like Vanta pXRF connected with RNDIS over USB cable
        #   host = "vanta-900000.local"         Device on network.  Name resolution needs to be working for this.
        #   host = "10.163.204.60"              Plain IP address if known.

        with open('configuration.json', 'r') as config_file:
            config = json.load(config_file)

        # If connection type is USB fix the host to 192.168.7.2
        if config['connection'] == 'USB':
            self.host = '192.168.7.2'
        else:
            self.host = config['host']
        self.port = config['port']

        self.controller = config['controller']
        if (self.controller):
            self.watchdog = config['watchdog']
        else:
            self.watchdog = False

        try:
            self.exit_headless = config['exit_headless']
        except:
            print("Error loading exit_headless from config file")
            self.exit_headless = False

        try:
            self.auto_login = config['auto_login']
        except:
            print("Error loading auto_login from config file")
            self.auto_login = False

        try:
            self.max_repeats = config['repeat_count']
        except:
            print("Error loading repeats from config file")
            self.max_repeats = 0

        try:
            self.repeat_sleep = config['repeat_sleep']
        except:
            print("Error loading repeats sleep from config file")
            self.repeat_sleep = 0


        try:
            self.repeat_calcheck = config['repeat_calcheck']
        except:
            print("Error loading repeat_calcheck from config file")
            self.repeat_calcheck = False

        try:
            self.dump_json = config['dump_json']
        except:
            print("Error loading dump_json from config file")
            self.dump_json = False

        try:
            self.dump_json_keep_all = config['dump_json_keep_all']
        except:
            print("Error loading dump_json_keep_all from config file")
            self.dump_json_keep_all = True

        try:
            self.dump_path_notifications = config['dump_path_notifications']
            self.dump_path_responses = config['dump_path_responses']
        except:
            # print("Error loading dump_path_notifications from config file")
            self.dump_path_notifications = ""
            self.dump_path_responses = ""

        try:
            self.login_username = config['username']
            self.login_password = config['password']
        except:
            print("Error loading username/password from config file")
            self.login_username = "Administrator"
            self.login_password = "0000"

        # Create the window
        QMainWindow.__init__(self, parent)
        title = 'Vanta ' + self.host
        self.setWindowTitle(title)

        # Construct the URL and create the websocket thread that will handle the communications.
        url = "ws://" + self.host + ":" + self.port
        self.websocket_thread = WebSocketThread(self, url, config['controller'], self.exit_headless)

        # Construct the UI layout and show it.
        self.create_main_frame()
        self.main_frame.show()

        # Create a timer that will trigger to keep UI updated.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_timer)
        self.timer_interval = 1000
        self.timer.start(self.timer_interval)

        self.on_draw()
        self.websocket_thread.start()
        self.repeat_test_checkbox.setChecked(self.repeat_tests)
        self.show_spectrum = True
        self.spectrum_initialized = False
        self.plot = None
        self.x1 = []
        self.y1 = []
        self.testCount = 0
        self.startTime = datetime.utcnow()

        self.header_re = re.compile("\[\D{4,5}\]\s0[xX][0-9a-fA-F]+")   # re.compile("\[\D{4,5}\]\s0[xX][0-9a-fA-F]+")
        self.last_message = 0
        self.beam_settings = {}     # empty json. Will fill this when we get list of settings from device.

        self.bytes_received = 0
        self.message_count = 0

        self.start_timestamp = datetime.utcnow()
        self.first_result_timestamp = datetime.utcnow()
        self.first_result = False

        # Bunch of variables to help debug method loading.
        self.method_load_count = 0
        self.method_load_start_time = datetime.utcnow()
        self.method_load_end_time = datetime.utcnow()

        if self.auto_login:
            self.on_login_clicked()

    def next_command_id(self):
        """
        Generate a new command id for each command we send.  This can be used to track responses.
        If we send a command to get something, the response should return our id.
        """
        self.command_id = self.command_id + 1
        return self.command_id

    def update_chemistry(self, data):
        """ Update the chemistry table """
        # print("update_chemistry")
        show_data = True
        if show_data:
            self.result_info_window.clear()
            try:
                calcheck = data['params']['result']['calCheckResult']
            except:
                pass

            if calcheck is not None:
                print(calcheck)
                calcheck_data = ""
                if calcheck['errorCode'] == 0:
                    error_str = "Passed"
                else:
                    error_str = "Failed"
                calcheck_data = calcheck_data + "CalCheck " + error_str + "\n"
                calcheck_data = calcheck_data + "Resolution: " + str(calcheck['resolution'])+"\n"
                calcheck_data = calcheck_data + "Count: " + str(calcheck['rate']) + "\n"
                calcheck_data = calcheck_data + "Slope " + str(calcheck['slope']) + "\n"
                calcheck_data = calcheck_data + "Offset: " + str(calcheck['offset']) + "\n"

                calcheck_data = calcheck_data + "Expected Resolution = " + str(calcheck['expectedResolution']) + "\n"
                calcheck_data = calcheck_data + "Expected Count = " + str(calcheck['expectedRate']) + "\n"
                calcheck_data = calcheck_data + "Expected Slope = " + str(calcheck['expectedSlope']) + "\n"
                calcheck_data = calcheck_data + "Expected Offset = "+str(calcheck['expectedOffset'])+"\n"

                self.result_info_window.append(calcheck_data)

            grades = data['params']['result']['gradeMatch']
            if len(grades):
                for g in grades:
                    # print ( g['gradeName'])
                    grade_item = "Grade = "+g['gradeName']+" Match = "+str(g['matchNumber'])+" "+g['matchMessage']
                    self.result_info_window.append(grade_item)

            chemistry = data['params']['result']['chemistry']

            self.chemistry_table.clearContents()
            self.chemistry_table.setRowCount(0)
            self.chemistry_table.update()
            self.chemistry_table.setRowHeight(0, 10)
            self.chemistry_table.setSortingEnabled(False)

            for element in chemistry:
                if element['concentration'] > 0:
                    self.chemistry_table.insertRow(0)
                    n = QTableWidgetItem(str(element['elementName']))
                    n.setTextAlignment(Qt.AlignRight)
                    self.chemistry_table.setItem(0, 0, n)

                    c = QTableWidgetItem('{:6.4f}'.format(element['concentration']))
                    c.setTextAlignment(Qt.AlignRight)

                    self.chemistry_table.setItem(0, 1, c)

                    e = QTableWidgetItem('{:6.4f}'.format(element['error']))
                    e.setTextAlignment(Qt.AlignRight)
                    self.chemistry_table.setItem(0, 2, e)

            self.chemistry_table.setSortingEnabled(True)
            self.chemistry_table.sortByColumn(1, Qt.DescendingOrder)
            self.chemistry_table.resizeRowsToContents()

            analysis = data['params']['result']['analysis']
            if analysis['latitude'] is not None:
                print(analysis['latitude'])
                print(analysis['longitude'])

    def display_spectrum(self, data):

        if self.show_spectrum:
            # Debug code to look at memory usage.
            # snapshot1 = tracemalloc.take_snapshot()

            # extract the spectrum data from the data.
            spectrum_data = data['params']['spectrum']
            slope = spectrum_data['energySlope']
            offset = spectrum_data['energyOffset']
            # live_time = spectrum_data['liveTime']

            # Make the energy scale from the slope and offset data.
            self.x1 = offset + slope * np.arange(2048)
            self.y1 = spectrum_data['data']
            label = "Beam-" + str(spectrum_data['exposureNumber'])
            if self. spectrum_initialized:
                self.plot.setData(self.x1, self.y1)
            else:
                self.plot = self.spectrum_plot.plot(self.x1, self.y1, pen=(0, 255, 255), name=label, clear="True")
                self.spectrum_initialized = True

#            Debug code to look at memory usage.
#            snapshot2 = tracemalloc.take_snapshot()
#            top_stats = snapshot2.compare_to(snapshot1, 'lineno')
#            print("[ Top 10 differences ]")
#            for stat in top_stats[:10]:
#                print(stat)
    def display_factory_spectrum(self, data):
        """Special case where the gain an offset are unknown so we hardcode them."""
        if self.show_spectrum:
            spectrum_data = data['params']['spectrum']
            slope = 20
            offset = 0
            #   Make the energy scale from the slope and offset data.
            self.x1 = offset + slope * np.arange(2048)
            self.y1 = spectrum_data
            label = "Factory"
            if self.spectrum_initialized:
                self.plot.setData(self.x1, self.y1)
            else:
                self.plot = self.spectrum_plot.plot(self.x1, self.y1, pen=(0, 255, 255), name=label, clear="True")
                self.spectrum_initialized = True

    def display_stability_spectrum(self, data):
        """Special case where the gain an offset are unknown so we hardcode them."""
        if self.show_spectrum:

            spectrum_data = data['params']['spectrum']
            slope = 20
            offset = 0
            #   Make the energy scale from the slope and offset data.
            self.x1 = offset + slope * np.arange(2048)
            self.y1 = spectrum_data
            label = "Stability"+str(data['params']['iteration'])
            if self.spectrum_initialized:
                self.plot.setData(self.x1, self.y1)
            else:
                self.plot = self.spectrum_plot.plot(self.x1, self.y1, pen=(0, 255, 255), name=label, clear="True")
                self.spectrum_initialized = True

    def log_battery_data(self, data):
        full_path = "battery.log"
        print("Battery Status {} {} {} {}".format(data['params']['mbRelStateOfCharge'],
                                               data['params']['mbStateOfCharge'],
                                               data['params']['mbCurrent'],
                                               data['params']['mbVoltage'] ))
        with open(full_path, 'a') as file:  # dump the data into a file for future access.


            payload = datetime.utcnow().isoformat() + "," \
                      + str(data['params']['mbRelStateOfCharge']) + "," \
                      + str(data['params']['mbStateOfCharge']) + "," \
                      + str(data['params']['mbCurrent']) + "," \
                      + str(data['params']['mbVoltage']) + "\n"
            file.write(payload)
            file.close()

    def notification_handler(self, data):    # messages with commandId of 403
        if self.dump_json:
            path = self.dump_path_notifications # "C:\\Users\\peter.hardman\\PycharmProjects\\Monitor\\notifications\\"
            notification_id = data["id"]
            foldername = str(notification_id)
            if self.dump_json_keep_all:
                filename = str(datetime.utcnow().strftime("%H %M %S"))+".json"
            else:
                filename = "sample.json"
            save_json(filename, path, foldername, data, True)

        #print(data["id"])
        if data["id"] == 100:
            # print("status", data)
            message = data["params"]["info"]+" "+data["params"]["systemStatus"]

            self.on_status_message_update(message)
            return
        # ------------------------------------
        if data["id"] == 101:
            print("hardwaremanagerNotificationStart", data)
            return
        # ------------------------------------
        if data["id"] == 103:
            #print("hardwaremanagerNotificationStart", data)
            self.log_battery_data(data)
            return
        # ------------------------------------
        if data["id"] == 104:
            print("DockedBatteryRemoved", data)
            return
        # ------------------------------------
        if data["id"] == 107:
            print("NotInHotSwapState", data)
            return
        # ------------------------------------
        if data["id"] == 109:
            print("DeviceUndocked", data)
            return
        # ------------------------------------
        if data["id"] == 109:
            print("DeviceUndocked", data)
            return
        # ------------------------------------
        if data["id"] == 110:
            print("DevicePluggedIntoAC", data)
            self.update_sdcard_status(data)
            return
        # ------------------------------------
        if data["id"] == 123:
            print("USBStorageStatusChanged", data)
            self.update_sdcard_status(data)
            return
        # ------------------------------------
        if data["id"] == 124:
            print("SDCardStatusChanged", data)
            self.update_sdcard_status(data)
            return
        # ------------------------------------
        if data["id"] == 125:
            print("WifiDongleStatusChanged", data)
            return
        # ------------------------------------
        if data["id"] == 126:
            print("EthernetStatusChanged", data)
            return
        # ------------------------------------
        if data["id"] == 127:
            print("EthernetDhcpStatusChanged", data)
            return
        # ------------------------------------
        if data["id"] == 129:
            print("DisplayOrientationChanged", data)
            return
            # ------------------------------------
        if data["id"] == 131:
            print("HardwareConfigurationChanged", data)
            self.update_sdcard_status(data)
            return
        # ------------------------------------
        if data["id"] == 132:
            self.update_hardware_status(data)
            return
        # ------------------------------------
        if data["id"] == 134:
            self.update_gps_status(data)
            return
        # ------------------------------------
        if data["id"] == 135:
            # print("ProximitySwitchStateChanged", data)
            return
        # ------------------------------------
        if data["id"] == 136:
            print("SafetySettingsChanged", data)
            return
        # ------------------------------------
        if data["id"] == 138:
            print("KeyStateChanged")
            return
        # ------------------------------------
        if data["id"] == 139:
            print("GPIOs changed", data)
            return
        # ------------------------------------

        if data["id"] == 200:
            print("Test Started")
            self.start_timestamp = datetime.utcnow()
            self.first_result = False
            if self.test_running is False:  # we got a test start?

                self.start_button.setText("Stop")
                self.test_running = True
            return
        # ------------------------------------
        if data["id"] == 201:
            print("Test Stopped")
            self.start_button.setText("Start")
            self.test_running = False
            pixmap = QPixmap('radiation_off.png')
            self.xray_status.setPixmap(pixmap)
            if self.repeat_tests and (self.testCount < self.max_repeats):
                #self.set_cloud_settings(False)
                #sleeps = 10*self.repeat_sleep
                start_time = datetime.now()
                while 1:
                    wait_time =datetime.now()-start_time
                    if wait_time.total_seconds() >= self.repeat_sleep:
                        break
                    else:
                        print(wait_time)
                        time.sleep(0.1)
                        self.pet_the_dog()
                        QApplication.processEvents()

                self.set_cloud_settings(True)
                if (self.repeat_calcheck):
                    self.on_calcheck_clicked()
                else:
                    #   self.set_beam_settings()    # Test code to send the beam settings before starting each test.
                    self.on_mode_clicked()      # Pretend the user selected a new method.
                    self.on_start_clicked()
            return
        # ------------------------------------
        if data["id"] == 202:
            # print("ExposureStarted",data)
            self.on_exposure_started(data)
            return
        # ------------------------------------
        if data["id"] == 203:
            # print("ExposureStopped",data)
            self.on_exposure_stopped(data)
            return
        # ------------------------------------
        if data["id"] == 204:
            # print("Spectrum")
            self.display_spectrum(data)
            return
        # ------------------------------------
        if data["id"] == 205:
            print("DiagnosticTraceReceived")
            return
        # ------------------------------------
        if data["id"] == 206:
            # print("Analysis result")
            if not self.first_result:
                self.first_result_timestamp = datetime.utcnow()
                print ("Time to first result = " , self.first_result_timestamp-self.start_timestamp)
                self.first_result = True
            self.update_chemistry(data)
            return
        # ------------------------------------
        if data["id"] == 207:
            # print("ExposureStatus",data)
            self.update_exposure_status(data)
            return
        # ------------------------------------
        if data["id"] == 208:
            print("CalCheckRequired")
            return
        # ------------------------------------
        if data["id"] == 209:
            print("ErrorDuringTest", data)
            return
        # ------------------------------------
        if data["id"] == 216:
            print("DriftCorrectionSettingUpdate", data)
            return
        # ------------------------------------
        #   Method Manager notifications start here
        # ------------------------------------
        if data["id"] == 300:
            # print("CurrentSettingsDataChanged", data)
            return
        # -------------------------------------
        if data["id"] == 301:
            # print("MethodLoaded ", data)

            # Test code to time how long a method took to load and then immediately ask for the method to be loaded again.
            self.method_load_count= self.method_load_count+1
            self.method_load_end_time = datetime.utcnow()
            difference = self.method_load_end_time - self.method_load_start_time

            load_time_seconds = difference.seconds + difference.microseconds/1000000.0
            print("{},{}, {},{}".format(self.method_load_count, load_time_seconds,
                                        self.method_load_start_time, self.method_load_end_time))
            if load_time_seconds < 0.5:
                print("Short Time!")
            self.method_load_start_time = datetime.utcnow()
            self.on_mode_clicked()

            # After method is loaded now you can request the beam settings for this new method.
            # self.get_beam_settings()  # Temporarily commented out for testing
            return
        # -------------------------------------
        if data["id"] == 302:
            # print("MethodLoading ", data)
            return
        # -------------------------------------
        if data["id"] == 306:
            # print("Method Changing ", data)
            return

        # ------------------------------------
        #   Result Manager notifications start here
        # ------------------------------------
        if data["id"] == 400:
            print("CalendarChanged")
            return
        # ------------------------------------
        if data["id"] == 406:
            print("testDateTime? ", data)
            return
        # ------------------------------------
        if data["id"] == 411:
            print("Queue update? ", data)
            self.set_cloud_settings(True)
            return
        # ------------------------------------
        #   Factory Manager notifications start here
        # ------------------------------------
        if data["id"] == 500:
            print("id=500")
            return
        if data["id"] == 501:
            message = "Factory Status: " + data["params"]["status"]
            self.on_status_message_update(message)
            return
        if data["id"] == 502:
            message = "Factory Progress: " + str(data["params"]["progress"])
            self.on_status_message_update(message)
            return

        if data["id"] == 513:
            print("StabilitySpectrumReady")
            self.display_stability_spectrum(data)

            return
        if data["id"] == 506:
            print("WorkOrderInfoChanged", data)
            return

        if data["id"] == 523:
            print("FactorySpectrumReady")
            self.display_factory_spectrum(data)
            return

        # ------------------------------------
        #   Result Manager notifications start here
        # ------------------------------------
        if data["id"] == 600:
            print("id=600")
            return
        # -------------------------------------
        if data["id"] == 604:
            # print("CloudStatusChanged")
            message = "CloudStatusChanged "+data["params"]["xrfString"]
            self.on_status_message_update(message)
            self.update_cloud_status(data)
            return
        # -------------------------------------
        if data["id"] == 610:
            print("ServiceRequestReceived")
            return
        # -------------------------------------
        if data["id"] == 616:
            print("UploadComplete")
            message = "UploadComplete"
            self.on_status_message_update(message)
            self.update_cloud_status(data)
            return
        # -------------------------------------
        if data["id"] == 617:
            print("UploadProgress")
            print(data)
            message = "UploadProgress " + str(data["params"]["xrfInt"]) + "%"
            self.on_status_message_update(message)
            self.update_cloud_status(data)
            return
        # -------------------------------------
        if data["id"] == 619:
            print("telemetrySettings")
            return
        # -------------------------------------
        if data["id"] == 620:
            print("DeviceRegistrationRequestReceived")
            return
        # -------------------------------------
        if data["id"] == 621:
            print("SoftwareUpdateStatusChanged")
            return
        # -------------------------------------
        if data["id"] == 636:
#           print("NetworkError")
            print("NetworkError", data)
            return

        # -------------------------------------


        # ------------------------------------
        #   Result Manager notifications start here
        # ------------------------------------
        if data["id"] == 701:
#            print("NewLogMessages")
#           print(data)
            self.update_log_messages(data)
            return
        # ------------------------------------
        if data["id"] == 702:
            print("Trigger pulled ")
            print(data)
            self.on_start_clicked()
            return
        # -------------------------------------

        if data["id"] == 704:
            print("Key pressed ")
            print(data)
            return
        # -------------------------------------
        if data["id"] == 771:
            print("BeamSettings")
            return
        # -------------------------------------
        print("Unhandled Notification ", data["id"], data)

    def response_handler(self, data):

        if self.dump_json:
            path = self.dump_path_responses  # "C:\\Users\\peter.hardman\\PycharmProjects\\Monitor\\responses\\"
            command_id = data["commandId"]
            foldername = str(command_id)
            if self.dump_json_keep_all:
                filename = str(datetime.utcnow().strftime("%H %M %S"))+".json"
            else:
                filename = "sample.json"
            save_json(filename, path, foldername, data, True)

        # print ("Response=",data["commandId"],)
        if data["commandId"] == 101:   # GetResults
            print("GetResults", data)
            return
        # -------------------------------------
        if data["commandId"] == 110:   # GetLatestNTestIds
            print("GetLatestNTestIds", data)
            return
        # -------------------------------------
        if data["commandId"] == 210:   # hardware update
            self.update_hardware_status(data)
            return
        # -------------------------------------
        if data["commandId"] == 301:    # login response
            print("login response", data)
            self.login_button.setText("Logout")
            self.logged_in = True
            self.on_login_occured()

            return
        # -------------------------------------
        if data["commandId"] == 319:  # logout response
            self.login_button.setText("Login")
            self.logged_in = False
            return
        # -------------------------------------
        if data["commandId"] == 317:    # user list response
            try:
                users = data["params"]["userIdList"]
                print(users)
            except:
                pass

            return
        # -------------------------------------
        if data["commandId"] == 407:    # GetRegulatoryRegion
            print("GetRegulatoryRegion",data)
            return
        # -------------------------------------
        if data["commandId"] == 408:    # SendKey
            print("Key pressed", data)
            return
        # -------------------------------------
        if data["commandId"] == 601:    # start response
            self.start_button.setText("Stop")
            self.test_running = True
            return
        # -------------------------------------
        if data["commandId"] == 602:    # stop response
            self.start_button.setText("Start")
            self.test_running = False
            return
        # -------------------------------------
        if data["commandId"] == 619:    # calcheckpromptenable
            print("GetCalCheckPromptEnable", data)
            return
        # -------------------------------------
        if data["commandId"] == 701:  # method list
            # print("method list= ", data)
            self.update_method_list(data)
            return
        # -------------------------------------
        if data["commandId"] == 702:  # current method
            print("current method= ", data)
            return
        # -------------------------------------
        if data["commandId"] == 771:    # beam settings
            # print("beam settings= ", data)
            self.beam_settings = data['params']
            return
        # -------------------------------------
        if data["commandId"] == 772:
            print("set beam settings response")
            return
        # -------------------------------------

        if data["commandId"] == 1001:
            self.update_log_messages(data)
            return
        # -------------------------------------
        if data["commandId"] == 1002:
            self.update_firmware_log(data)
            return
        # -------------------------------------
        if data["commandId"] == 1003:
            self.update_sdcard_space(data)
            return
        # -------------------------------------
        if data["commandId"] == 253:    # get_faults response
            faults = data["params"]["faults"]
            if len(faults):
                print(faults)
            else:
                print("empty faults list")
            return
        # -------------------------------------
        if data["commandId"] == 254:    # clear_faults response
            print("clear faults response")
            return
        # -------------------------------------

        print("Unhandled command ", data["commandId"], data)

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

        if data["commandId"] == 403:
            self.notification_handler(data)
        else:
            self.response_handler(data)

    def update_exposure_status(self, data):
        # update a progress bar based on the values in the data.
        pass

    def on_exposure_started(self, data):
        pass

    def on_exposure_stopped(self, data):
        self.get_faults()
        pass

    def update_cloud_status(self, data):
        if data["id"] == 604:
            status = data["params"]["xrfString"]
            if(status == "ConnectedToCloud") or (status == 'ConnectedAndSendingRequests'):
                if status == "ConnectedToCloud":
                    pixmap = QPixmap('cloud.png')
                    self.cloud_status.setPixmap(pixmap)
                if status == "ConnectedAndSendingRequests":
                    pixmap = QPixmap('cloud_up.png')
                    self.cloud_status.setPixmap(pixmap)
            else:
                pixmap = QPixmap('cloud_off.png')
                self.cloud_status.setPixmap(pixmap)
            return
        if data["id"] == 617:
            if data["params"]["xrfInt"] < 100:
                pixmap = QPixmap('cloud_up.png')
                self.cloud_status.setPixmap(pixmap)
            else:
                pixmap = QPixmap('cloud.png')
                self.cloud_status.setPixmap(pixmap)

    def update_sdcard_space(self, data):
        # {'commandId': 1003, 'id': 2, 'params': {'freeSpace': 574205952,
        #                                           'percent': 35.57079315185547,
        #                                           'totalSpace': 891219968}
        #                                        }
        pass

    def update_sdcard_status(self, data):
        if data["id"] == 124:
            if data["params"]["status"] is True:
                pixmap = QPixmap('sdcard_in.png')
                self.sdcard_status.setPixmap(pixmap)
            else:
                pixmap = QPixmap('sdcard_out.png')
                self.sdcard_status.setPixmap(pixmap)
        if data["id"] == 131:
            if data["params"]["hasSDCard"] is True:
                pixmap = QPixmap('sdcard_in.png')
                self.sdcard_status.setPixmap(pixmap)
            else:
                pixmap = QPixmap('sdcard_out.png')
                self.sdcard_status.setPixmap(pixmap)

    def update_hardware_status(self, data):
        # ToDo implement a graphical view of the hardware status data.
        # print(data)
        show_data = True
        if show_data:
            hardware_status = data['params']

            self.hardware_table.clearContents()
            self.hardware_table.setRowCount(0)
            self.hardware_table.update()
            self.hardware_table.setRowHeight(0, 10)
            self.hardware_table.setSortingEnabled(False)

            for param in hardware_status:

                self.hardware_table.insertRow(0)
                p = QTableWidgetItem(str(param))
                p.setTextAlignment(Qt.AlignRight)
                self.hardware_table.setItem(0, 0, p)
                value = hardware_status[param]
                v = QTableWidgetItem('{:6.2f}'.format(float(value)))

                v.setTextAlignment(Qt.AlignRight)
                self.hardware_table.setItem(0, 1, v)

            # self.hardware_table.setSortingEnabled(True)
            # self.hardware_table.sortByColumn(1, 1)
            self.hardware_table.resizeRowsToContents()

    def update_gps_status(self, data):
        # ToDo implement a view of the gpsInfo data.
        # print("gps",data)
        pass

    def update_method_list(self, data):
        print("methods", data)
        methods = data['params']['methodList']
        for m in methods:
            self.method_combo.addItem(m['id'])

    def update_log_messages(self, data):
        messages = data['params']['messages']
        for m in messages:

            if m.find('INFO', 0, len(m)) > 0:
                self.log_window.setTextColor(Qt.darkGray)
            if m.find('DEBUG', 0, len(m)) > 0:
                self.log_window.setTextColor(Qt.darkGreen)
            if m.find('WARNING', 0, len(m)) > 0:
                self.log_window.setTextColor(Qt.darkBlue)
            if m.find('CRITICAL', 0, len(m)) > 0:
                self.log_window.setTextColor(Qt.darkRed)

            self.log_window.append(m)
            self.write_log_file(m + "\n")
            # print("log-message",m)

        # code below was added to confirm that we reach the block limit set in construction of the QTextEdit object
        # lineCount=self.log_window.document().blockCount()
        # print(lineCount)

    def update_firmware_log(self, data):
        new_message = data['params']['log']
        new_message_list = re.split("\n", new_message)  # split into list so we can sort
        out_message_list = []

        for n in range(len(new_message_list)):
            header = self.header_re.search(new_message_list[n])
            try:
                header_split = re.split("\s", header.group())  # turn [INFO] 0xDEADBEEF into 0xDEADBEEF
                if len(header_split[1]) != 10:
                    print("Unexpected timestamp! format.", header_split[1])
                else:
                    timestamp_read = int(header_split[1], 0)
                    if (timestamp_read < 0xFFFFFFFF) and (timestamp_read > 0x00000000):
                        if self.last_message < timestamp_read:
                            out_message_list.append(new_message_list[n])
                            self.last_message = timestamp_read
                        else:   # check for wrap-around of the time. Which happens every 5 days or so.
                            if (0xFFFFFFFF - self.last_message) < 0x10000:
                                print("wrap around might have happened. Old & new=", self.last_message, timestamp_read)
                                self.last_message = timestamp_read
                            else:
                                pass
                                # print("rejecting based on timestamp ",self.last_message,timestamp_read)
                    else:
                        print("unexpected timestamp!", timestamp_read)
                        out_message_list.append(new_message_list[n])
            except:
                pass

        if out_message_list:
            for m in out_message_list:

                if m.find('WARN', 0, len(m)) > 0:
                    self.firmware_log_window.setTextColor(Qt.darkBlue)
                if m.find('INFO', 0, len(m)) > 0:
                    self.firmware_log_window.setTextColor(Qt.black)
                if m.find('ERROR', 0, len(m)) > 0:
                    self.firmware_log_window.setTextColor(Qt.red)
                self.firmware_log_window.append(m)

            out_message = "\n".join(out_message_list)
            self.write_firmware_log_file(out_message + "\n")
        else:
            pass

    def on_calcheck_clicked(self):
        print("CalCheckClicked")
        command = dict()
        command['commandId'] = 606
        command['id'] = 12345
        command['params'] = {}
        self.websocket_thread.send_command(command)

        self.testCount = self.testCount + 1
        pixmap = QPixmap('radiation_on.png')
        self.xray_status.setPixmap(pixmap)

    def on_test_times_clicked(self):
        dlg = TestTimeDialog(None, self.beam_settings)  # If you pass self, the dialog will be centered over the main window as before.
        if dlg.exec_():
            print("Success! Value = {}".format(dlg.beam_settings))
            self.beam_settings=dlg.beam_settings
            self.set_beam_settings()
        else:
            print("Cancel! Value = {}".format(dlg.beam_settings))

    def on_start_clicked(self):
        """Contruct a start or stop command based on the current status of the unit."""
        self.clear_faults()
        if self.test_running is False:
            print("start button clicked")
            self.clear_faults()
            command = dict()
            command['commandId'] = 601
            command['id'] = 12345
            command['params'] = {}

            self.testCount = self.testCount + 1
            pixmap = QPixmap('radiation_on.png')
            self.xray_status.setPixmap(pixmap)


        else:
            print("stop button clicked")
            command = dict()
            command['commandId'] = 602
            command['id'] = 12345
            command['params'] = {}
            pixmap = QPixmap('radiation_off.png')
            self.xray_status.setPixmap(pixmap)

        self.websocket_thread.send_command(command)

    def send_basic_command(self, command_id):
        command = dict()
        command["commandId"] = command_id
        command["id"] = 0
        command["params"] = {}
        self.websocket_thread.send_command(command)

    def on_login_occured(self):
        time.sleep(0.5)

    #   Send a basic command which has no parameters.


#   Next block is an attempt to emulate the PC_SW and see what kinds of responses we get.

        self.send_basic_command(407)
        self.send_basic_command(1003)
#        self.send_basic_command(317)
#        self.send_basic_command(246)
#        self.send_basic_command(201)
#        self.send_basic_command(218)
#        self.send_basic_command(1326)
#        self.send_basic_command(211)F
#        self.send_basic_command(211)
#        self.send_basic_command(1104)
#        self.send_basic_command(1106)
#        self.send_basic_command(245)
#        self.send_basic_command(211)
#        self.send_basic_command(406)
#        self.send_basic_command(211)
#        self.send_basic_command(225)
#        self.send_basic_command(244)

#   End of PC SW emulation

        self.get_faults()
        self.get_user_list()
        self.get_method_list()
        self.get_current_method()
        self.get_beam_settings()

    def on_login_clicked(self):
        # ToDo   Allow user and password selection.
        # Currently hardcoded to Factory 1234
        if self.logged_in is False:
            print("login button clicked")
            command = dict()
            command['commandId'] = 301
            command['id'] = 0
            params = dict()
            params["userId"] = str(self.login_username)
            params["password"] = str(self.login_password)
            command['params'] = params

        else:
            print("logout button clicked")
            self.login_button.setText("Login")
            self.logged_in = False
            command = dict()
            command["commandId"] = 319
            command["id"] = 0
            command["params"] = {}

        self.websocket_thread.send_command(command)

    def on_shutdown_clicked(self):
        print("shutdown button clicked")
        command = dict()
        command["commandId"] = 405
        command["id"] = 0
        command["params"] = {}
        self.websocket_thread.send_command(command)

    def pet_the_dog(self):
        #print("Woof!")
        self.send_basic_command(244)

    def get_beam_settings(self):
        self.send_basic_command(771)

    def set_beam_settings(self):
        command = dict()
        command["commandId"] = 772
        command["id"] = 0
        command["params"] = self.beam_settings
        self.websocket_thread.send_command(command)

    def on_method_combo_changed(self):
        method = self.method_combo.itemText(self.method_combo.currentIndex())
        print("Method Selected=", method)

    def on_mode_clicked(self):
        # ToDo   Allow mode selection.
        selected_method = self.method_combo.itemText(self.method_combo.currentIndex())
        #print(selected_method)
        command = dict()
        command["commandId"] = 703
        command["id"] = 0
        command["params"] = {"methodId": selected_method}
        self.websocket_thread.send_command(command)


    def get_work_order(self):
        self.send_basic_command(1106)

    def get_faults(self):
        self.send_basic_command(253)

    def clear_faults(self):
        self.send_basic_command(254)

    def get_user_list(self):
        self.send_basic_command(317)

    def get_firmware_log(self):
        self.send_basic_command(1002)

    def get_log(self):
        self.send_basic_command(1001)

    def get_method_list(self):
        self.send_basic_command(701)

    def get_current_method(self):
        self.send_basic_command(702)

    def set_cloud_settings(self, enable):
        command = dict()
        command["commandId"] = 778
        command["id"] = 0
        if enable is True:
            command["params"] = {"enabled": "true"}
        else:
            command["params"] = {"enabled": "false"}
        self.websocket_thread.send_command(command)

    def get_hardware_status(self):
        self.send_basic_command(210)

    def on_timer(self):
        """
        Do some things on a regular basis to make sure we get the data.  For example we have to pet the watchdog,
        and ask for the hardware status and logs.
        """
#        print("message count = {}, bytes = {}".format(self.message_count, self.bytes_received))

        if not self.initiated:
            if self.websocket_thread.ws.connected:
                #   self.get_user_list()
                #   self.get_method_list()
                #   self.get_current_method()
                #   self.get_beam_settings()
                # self.set_cloud_settings(False)
                time.sleep(1)
                self.set_cloud_settings(True)
                self.initiated = True

        if self.websocket_thread.ws.connected:
            self.get_hardware_status()
            self.get_firmware_log()
 #           self.send_basic_command(244)
 #           self.get_log()
            self.update_uptime()
            self.update_bytes()
            if self.watchdog:
                self.pet_the_dog()
            pass

    @staticmethod
    def on_draw():
        print('OnDraw')

    def on_status_message_update(self, message):
        # print ("on_status_message_update",message)
        self.status_bar.showMessage(str(message))
        self.status_bar.repaint()

    def update_uptime(self):
        cur_time = datetime.utcnow()
        time_delta = cur_time - self.startTime
        message = "Uptime = " + str(time_delta).split('.')[0] + " Cycles = "+str(self.testCount)
        self.uptime_bar.showMessage(str(message))
        self.uptime_bar.repaint()

    def update_bytes(self):
        b = self.bytes_received
        suffix = " "
        if self.bytes_received < (1024*1024*1024*1024):  # G-bytes
            b = self.bytes_received/(1024*1024*1024)
            suffix = "G"
        if self.bytes_received < (1024*1024*1024):  # M-bytes
            b = self.bytes_received/(1024*1024)
            suffix = "M"
        if self.bytes_received < 1024*1024:  # K-bytes
            b = self.bytes_received/1024
            suffix = "K"
        if self.bytes_received < 10*1024:  # Bytes
            b = self.bytes_received
            suffix = "bytes"

        message = "Messages = " + str(self.message_count)+" Transfered = " + format(b, "0.2f") + suffix
        self.bytes_bar.showMessage(str(message))
        self.bytes_bar.repaint()

    def on_repeat_checked(self):
        if self.repeat_test_checkbox.isChecked():
            self.repeat_tests = True
        else:
            self.repeat_tests = False
        print("repeats", self.repeat_tests)

    def on_show_spectrum_checked(self):
        if self.show_spectrum_checkbox.isChecked():
            self.show_spectrum = True
        else:
            self.show_spectrum = False
        print("show spectrum", self.show_spectrum)


    def write_log_file(self, message):
        log_name=self.host+'_SW_log.txt'
        with open(log_name, 'a') as logfile:
            logfile.write(message)
            logfile.close()

    def write_firmware_log_file(self,message):
        log_name = self.host + '_firmware_log.txt'
        with open(log_name, 'a') as logfile:
            logfile.write(message)
            logfile.close()

    def create_main_frame(self):

        max_log_length = 250
        self.main_frame = QWidget()
        self.log_font = QFont("Courier", 6)

        self.log_window = QTextEdit()
        self.log_window.setWordWrapMode(QTextOption.NoWrap)
        self.log_window.setCurrentFont(self.log_font)
        self.log_window.setFontPointSize(8)
        self.log_window.document().setMaximumBlockCount(max_log_length)

        self.firmware_log_window = QTextEdit()
        self.firmware_log_window.setWordWrapMode(QTextOption.NoWrap)
        self.firmware_log_window.setCurrentFont(self.log_font)
        self.firmware_log_window.setFontPointSize(8)
        self.firmware_log_window.document().setMaximumBlockCount(max_log_length)

        self.logs_splitter = QSplitter()
        self.logs_splitter.addWidget(self.log_window)
        self.logs_splitter.addWidget(self.firmware_log_window)

        # -----------------------------------------------
        # Create spectrum plot window
        # -----------------------------------------------
        self.spectrum_plot_layout = QSplitter()
        self.spectrum_plot_layout.setOrientation(Qt.Vertical)

        self.spectrum_view = pg.GraphicsLayoutWidget()
        self.spectrum_plot = self.spectrum_view.addPlot(title="Spectrum", pen=(0, 255, 255), name="spectrum")
        self.spectrum_plot_layout.addWidget(self.spectrum_view)
        self.spectrum_plot_layout.addWidget(self.logs_splitter)

        # -----------------------------------------------
        # Create HW data table
        # -----------------------------------------------
        self.hardware_table = QTableWidget(0, 2)
        self.hardware_table.setMinimumWidth(210)
        self.hardware_table.setMaximumWidth(280)
        self.hardware_table.setMinimumHeight(50)
        self.hardware_table.setHorizontalHeaderLabels(
            ['Parameter', 'Value'])

        self.hardware_table.setColumnWidth(0, 140)  # parameter name
        self.hardware_table.setColumnWidth(1, 70)  # value

        # -----------------------------------------------
        # Create info window.  Grade + other things.
        # -----------------------------------------------
        self.result_info_window = QTextEdit()
        self.result_info_window.setWordWrapMode(QTextOption.NoWrap)
        self.result_info_window.setCurrentFont(self.log_font)
        self.result_info_window.setFontPointSize(8)
        self.result_info_window.setMinimumHeight(50)
        self.result_info_window.setMinimumWidth(210)
        self.result_info_window.setMaximumWidth(280)
        # -----------------------------------------------
        # Create chemistry table
        # -----------------------------------------------
        self.chemistry_table = QTableWidget(0, 3)
        self.chemistry_table.setMinimumWidth(210)
        self.chemistry_table.setMaximumWidth(280)
        self.chemistry_table.setMinimumHeight(50)
        self.chemistry_table.setHorizontalHeaderLabels(
            ['Z', 'Conc', 'Err'])

        self.chemistry_table.setColumnWidth(0, 40)  # Element
        self.chemistry_table.setColumnWidth(1, 70)  # Concentration
        self.chemistry_table.setColumnWidth(2, 70)  # Error
        self.chemistry_table.sortByColumn(1, Qt.AscendingOrder)

        self.data_layout = QSplitter()
        self.data_layout.setOrientation(Qt.Vertical)
        self.data_layout.addWidget(self.hardware_table)
        self.data_layout.addWidget(self.result_info_window)
        self.data_layout.addWidget(self.chemistry_table)

        # -----------------------------------------------
        # Create Final layout of spectrum and data
        # -----------------------------------------------
        self.results_layout = QHBoxLayout()
        self.results_layout.addWidget(self.spectrum_plot_layout)
        self.results_layout.addWidget(self.data_layout)

        # -----------------------------------------------
        # Create buttons
        # -----------------------------------------------
        BUTTON_WIDTH = 80
        self.start_button = QPushButton("Start")
        self.start_button.setMinimumWidth(BUTTON_WIDTH)
        self.start_button.setMaximumWidth(BUTTON_WIDTH)

        self.calcheck_button = QPushButton("CalCheck")
        self.calcheck_button.setMinimumWidth(BUTTON_WIDTH)
        self.calcheck_button.setMaximumWidth(BUTTON_WIDTH)

        self.method_button = QPushButton("Select Method")
        self.method_button.setMinimumWidth(BUTTON_WIDTH)
        self.method_button.setMaximumWidth(BUTTON_WIDTH)

        self.login_button = QPushButton("login")
        self.login_button.setMinimumWidth(BUTTON_WIDTH)
        self.login_button.setMaximumWidth(BUTTON_WIDTH)

        self.shutdown_button = QPushButton("shutdown")
        self.shutdown_button.setMinimumWidth(BUTTON_WIDTH)
        self.shutdown_button.setMaximumWidth(BUTTON_WIDTH)

        self.test_times_button = QPushButton("Test Times")
        self.test_times_button.setMinimumWidth(BUTTON_WIDTH)
        self.test_times_button.setMaximumWidth(BUTTON_WIDTH)

        self.method_combo = QComboBox()
        self.method_combo.setMaximumWidth(120)
        self.method_combo.currentIndexChanged.connect(self.on_method_combo_changed)

        self.repeat_test_checkbox = QCheckBox("Repeat")
#        self.show_spectrum_checkbox = QCheckBox("Show Spectrum")

        # -----------------------------------------------
        # Add group log and plot to HBox
        # -----------------------------------------------
        data_box = QHBoxLayout()
        data_box.addWidget(self.shutdown_button)
        data_box.addWidget(self.login_button)
        data_box.addWidget(self.method_combo)
        data_box.addWidget(self.method_button)
        data_box.addWidget(self.test_times_button)

        data_box.addWidget(self.start_button)
        data_box.addWidget(self.calcheck_button)
        data_box.addWidget(self.repeat_test_checkbox)
#        data_box.addWidget(self.show_spectrum_checkbox)

        # -----------------------------------------------
        # Create status bar
        # -----------------------------------------------
        self.status_bar = QStatusBar()
        self.status_bar.setMinimumWidth(300)

        self.uptime_bar = QStatusBar()
        self.uptime_bar.setMinimumWidth(50)

        self.bytes_bar = QStatusBar()
        self.bytes_bar.setMinimumWidth(50)

        self.cloud_status = QLabel(self)
        pixmap = QPixmap('cloud_off.png')
        self.cloud_status.setPixmap(pixmap)

        self.sdcard_status = QLabel(self)
        pixmap = QPixmap('sdcard_out.png')
        self.sdcard_status.setPixmap(pixmap)

        self.xray_status = QLabel(self)
        pixmap2 = QPixmap('radiation_off.png')
        self.xray_status.setPixmap(pixmap2)

        status_box = QHBoxLayout()
        status_box.addWidget(self.xray_status)
        status_box.addWidget(self.cloud_status)
        status_box.addWidget(self.sdcard_status)
        status_box.addWidget(self.status_bar)
        status_box.addStretch()
        status_box.addWidget(self.uptime_bar)
        status_box.addWidget(self.bytes_bar)
        # -----------------------------------------------
        # Put all together
        # -----------------------------------------------

        vbox = QVBoxLayout()
#        vbox.addLayout(self.spectrum_plot_layout)
        vbox.addLayout(self.results_layout)
        vbox.addLayout(data_box)
        vbox.addLayout(status_box)

        self.main_frame.setLayout(vbox)
        self.setCentralWidget(self.main_frame)
        self.calcheck_button.clicked.connect(self.on_calcheck_clicked)
        self.start_button.clicked.connect(self.on_start_clicked)
        self.method_button.clicked.connect(self.on_mode_clicked)
        self.login_button.clicked.connect(self.on_login_clicked)
        self.shutdown_button.clicked.connect(self.on_shutdown_clicked)
        self.test_times_button.clicked.connect(self.on_test_times_clicked)
        self.repeat_test_checkbox.clicked.connect(self.on_repeat_checked)

        #   One of the most important lines!  Here we connect the notification signal emitted by the websocket thread
        #   to the message_dispatcher function.
        self.websocket_thread.notification.connect(self.message_dispatcher)


def run_application():
    app = QApplication(sys.argv)
    form = AppForm()
    form.show()
    app.exec_()


if __name__ == "__main__":
    run_application()
    print("The end")
