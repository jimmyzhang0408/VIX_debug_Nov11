# Handling trigger events and GPIO signals in an application
Olympus XRF API


Last updated 5-August 2021 


## Introduction.
The Vanta instrument has a trigger that the user can pull to signal a test should start or stop. Vanta iX has a GPIO signal on the Olympus GPIO port that can accomplish the same function.
Both of these hardware inputs produce events in the software that need to be handled by the controlling code that is using the API.  For a standalone Vanta running with the built in device software this is done by the UI. For a Vanta or Vanta iX controlled by the PC Software these events are handled by the PC SW. If you are writing your own code to start and stop tests in response to a trigger or start/stop GPIO signal you need to handle these API notifications yourself and call  the corresponding start commands. 

### Details.
When the trigger is pulled or the start/stop GPIO is pressed the API generates a notification event [notification id =704](API-Command-List.md)

So the code needs to handle this notification and turn it into a start or stop command, depending on the internal state machine of the system.

Here is some example python code from the python example that shows how this can be handled. The params field contains the keystroke which occurred. 
A value of 6 indicates start was pressed (or trigger pulled). A value of 7 indicates start (or trigger) was released. 

        # ------------------------------------
        if data["id"] == 704:
            print("Key pressed ")
            print(data)
            if data["params"]["keyActivated"] == 6:
                print("Start pressed")
                self.on_start_clicked()
            if data["params"]["keyActivated"] == 7:
                print("Start released")
                pass
            return
        # -------------------------------------

In this example the code decides to react only to the press and not the release, and calls the function on_start_clicked()
Here is what this code might look like. 

    def on_start_clicked(self):
        """Contruct a start or stop command based on the current status of the unit."""
        if self.test_running is False:
            print("start button clicked")
            self.clear_faults()
            command = dict()
            command['commandId'] = 601
            command['id'] = 12345
            command['params'] = {}

            self.testCount = self.testCount + 1

        else:
            print("stop button clicked")
            command = dict()
            command['commandId'] = 602
            command['id'] = 12345
            command['params'] = {}

        self.websocket_thread.send_command(command)

The code checks to see if a test is already running. If not it sends a start command id =601, otherwise it sends a stop command id=602
