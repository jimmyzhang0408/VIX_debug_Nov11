# Olympus XRF API 
Command and Notification Reference List

## API Reference

#### Commands
| Command | ID|
|---------------------|------------------|
|<a href= #GetImage >Get Image</a>| 115|
| | |
|<a href="#RefreshHardwareConfiguration">Refresh Hardware Configuration</a>| 211|
|<a href="#SetSystemTime">Set System Time</a>| 230|
|<a href="#PetWatchdog">Pet Watchdog</a>| 244|
|<a href="#SetDigitalIOState">Set Digital I/O State</a>| 251|
|<a href="#GetDigitalIOState">Get Digital I/O State</a>| 252|
|<a href="#GetFaults">Get Faults</a>| 253|
|<a href="#ClearFaults">Clear Faults</a>| 254|
| | |
|<a href="#Login">Login</a>| 301|
|<a href="#GetUserList">Get User List</a>| 317|
|<a href="#Logout">Logout</a>| 319|
| | |
|<a href="#Logout">Shutdown</a>| 405|
|<a href="#About">About</a>| 406|
|<a href="#StartTest">Start Test</a>| 601|
|<a href="#StopTest">Stop Test</a>| 602|
|<a href="#SetTestInfoField">Set Test Info Field</a>| 604|
|<a href="#StartCalCheck">Start Cal Check</a>| 606|
| | |
|<a href="#GetMethodList">Get Method List</a>| 701|
|<a href="#GetCurrentMethod">Get Current Method</a>| 702|
|<a href="#SetCurrentMethod">Set Current Method</a>| 703|
| | |
|<a href="#RemoveGradeLibrary">Remove Grade Library</a>| 709|
|<a href="#GetGradeLibraryList">Get Grade Library List</a>| 722|
|<a href="#GetGradeListByBase">Get Grade List by Base</a>| 723|
| | |
|<a href="#SetMethodDisplaySettings">Set Method Display Settings</a>| 738|
|<a href="#GetGradeMatchSettings">Get Grade Match Settings</a>| 744|
|<a href="#SetGradeMatchSettings">Set Grade Match Settings</a>| 745|
|<a href="#GetUserFactorTemplateList">Get User Factor Template List</a>| 750|
|<a href="#SetActiveUserFactor">Set ActiveUser Factor</a>| 756|
|<a href="#GetActiveUserFactor">Get ActiveUser Factor</a>| 757|
|<a href="#GetBeamConfiguration">Get Beam Configuration</a>| 771|
|<a href="#SetBeamConfiguration">Set Beam Configuration</a>| 772|
|<a href="#SetCloudSettings">Set Cloud Settings</a>| 778|
| | |
|<a href="#ImportGradeLibFromCsvV2">Import Grade Library from CSV</a>| 832|
| | |
|<a href="#GetSDCardPercentOccupied">Get SD card % occupied</a>| 1003|
|<a href="#SetLoggerLevel">Set Logger Level</a>| 1005|
|<a href="#DeployLANConfig">Deploy LAN configuration</a>| 1348|
|<a href="#ClearNetworkSettings">Clear Network Settings</a>| 1349|
---

#### Notifications
| Notification | ID|
|----------|----------|
|<a href="#SystemStatus">System status message</a>| 100|
|<a href="#BatteryStatus">Battery status message</a>| 103|
|<a href="#DevicePluggedIntoAC">DC Power is connected</a>| 110|
|<a href="#DeviceDisconnectedFromAC">DC Power is removed</a>| 111|
|<a href="#HardwareConfigurationChanged">Hardware Configuration Changed</a>| 131|
|<a href="#DigitalIOStateChanged">Digital IO state Changed</a>| 139|
|<a href="#TestStarted">Test Started</a>| 200|
|<a href="#TestStopped">Test Stopped</a>| 201|
|<a href="#ExposureStarted">Exposure Started</a>| 202|
|<a href="#ExposureStopped">Exposure Stopped</a>| 203|
|<a href="#SpectrumUpdate">Spectrum update</a>| 204|
|<a href="#ResultReceived">Result Received</a>| 206|
|<a href="#ExposureStatus">Exposure Status</a>| 207|
|<a href="#ErrorDuringTest">Error During Test</a>| 209|
|<a href="#SettingsChanged">Settings Changed</a>| 300|
|<a href="#MethodLoaded">Method Loaded</a>| 301|
|<a href="#MethodLoading">Method Loading</a>| 302|
|<a href="#NewLogMessages">New Log Messages</a>| 701|
|<a href="#TriggerPulled">Trigger Pulled</a>| 702|
|<a href="#KeyPressed">Key Pressed</a>| 704|
|<a href="#BeamSettingsChanged">Beam Settings Changed</a>| 771|

---

<p id="#Commands"></p>

### Commands

---

<p id="SetDigitalIOState"></p>

#### Set Digital I/O State

Used to set the state of the digital inputs and outputs. (See <a href="#DigitalIOStateChanged">DigitalIOStateChanged</a> for an explanation of the I/O banks.)

*Note*: Only applicable to Vanta-iX.

**Command:**

```json
{
    "commandId": 251,
    "id": 1234,
    "params": {
        "bank1": 145,
        "bank2": 230,
        "bank3": 192,
        "bank4": 128
    }
}
```

**Response:**

none

---

<p id="GetDigitalIOState"></p>

#### Get Digital I/O State

Used to query the state of the digital inputs and outputs. (See <a href="#DigitalIOStateChanged">DigitalIOStateChanged</a> for an explanation of the I/O banks.)

*Note*: Only applicable to Vanta-iX.

**Command:**
```json
{
    "commandId": 252,
    "id": 1234,
    "params": {}
}
```

**Response:**
```json
{
    "commandId": 252,
    "id": 1234,
    "params": {
        "bank1": 145,
        "bank2": 230,
        "bank3": 192,
        "bank4": 128
    }
}
```

---

<p id="GetFaults"></p>

#### Get Faults 

Used to request a list of faults that the system may have issued.

**Command:**
```json
{
    "commandId": 253,
    "id": 1234,
    "params": {
    }
}
```
**Response:**
If there are faults they will be returned as an array of fault codes, and fault strings.

```json
{
    "commandId": 253,
    "id": 1234,
    "params": {
        "faultCodes": [18, 112], 
        "faults": ["Tube interlock broken", "Exposure fault"]
    }
}
```

---

<p id="ClearFaults"></p>

#### Clear Faults 
Used to clear any faults that the system may have issued. Recommended to do this before starting a test.

**Command:**

```json
{
    "commandId": 254,
    "id": 1234,
    "params": {
    }
}
```

**Response:**

```json
{
    "commandId": 254,
    "id": 1234,
    "params": {
    }
}
```

---

<p id="Login"></p>

#### Login 

Used to start a session. The login information (user ID, password) is the same as what is used to log in to the instrument using the on-device application and Vanta PC software.

**Command:**

```json
{
    "commandId": 301,
    "id": 1234,
    "params": {
        "userId": "Administrator",
        "password": "0000"
    }
}
```
After sending the login command, the middleware will send a response that is a simple string with the following format, before the JSON formatted response.

"checksum:5d2f4290178c593f1a50cf15345fdcdb"

This message can be ignored. It contains a GUID that summarizes the current version of all the installed SW packages and is used for compatibility validation by our own SW.  Following this message you will get the standard JSON response.

**Response:**

```json
{
    "commandId": 301, 
    "id": 1, 
    "params": {
        "headless": false, 
        "language": "", 
        "password": "0000", 
        "userId": "Administrator", 
        "userType": 1, 
        "withSound": true
    }
}
```
If incorrect credentials are supplied the response will contain error message,and additional information. Example below.

```json
{
    "commandId": 301,
    "error": {
    "errorCode": -3999,
    "errorString": "Invalid password", "errorType": 0} ,
    "id": 1234,
    "params": {
        "headless": false, 
        "language": "", 
        "password": "9999", 
        "userId": "Administrator", 
        "userType": 0, 
        "withSound": true
        }
    }
}
```
---

<p id="GetUserList"></p>

#### GetUserList 
Used to get a list of users loaded onto the device, that can be used to log into the device.
**Command:**
```json
{
    "commandId": 317,
    "id": 1234,
    "params": {}
}
 ```
 **Response:**
```json
{
    "commandId": 317,
    "id": 1234,
    "params": {
        "langList": "en,en,en",
        "userIdList": "Administrator,user2,user3"
    }
}
```

---

<p id="Logout"></p>

#### Logout 

Used to end a session. The response is identical to the command.

**Command / Response:**

```json
{
    "commandId": 319,
    "id": 1234,
    "params": {
    }
}
```

---

<p id="Shutdown"></p>

#### Shutdown 

Used to power down the unit. There is no response because the unit is powering down and closing the connection.

**Command / Response:**

```json
{
    "commandId": 405,
    "id": 1234,
    "params": {
    }
}
```
---

<p id="about"></p>

#### About 

Returns a lot of data, like the OS build, FW version, etc. The key with the human-readable SW version will be named “appSoftwareVersion”.

**Command / Response:**

```json
{
    "commandId": 406,
    "id": 1234,
    "params": {
    }
}
```
---

<p id="StartTest"></p>

#### StartTest 

Used to start an XRF test. The response is identical to the command.

**Command:**

```json
{
    "commandId": 601,
    "id": 1234,
    "params": {
    }
}
```

**Response:**

none

---

<p id="StopTest"></p>

#### StopTest 

Used to stop an XRF test. The response is identical to the command.

**Command / Response:**

```json
{
    "commandId": 602,
    "id": 1234,
    "params": {
    }
}
```

---

<p id="StartCalCheck"></p>

#### StartCalCheck 

Used to start a cal check. The response is identical to the command.
A cal check is used to verify that peak locations in the spectrum have not drifted, that the calibrated slope and offset of the spectrum have not changed, and that the overall count rate while shooting a SS316 sample has not changed. 
> Note: On a Vanta iX the system will use the internal shutter for this test. If you are using the API with a Vanta handheld, please remember to place a SS316 sample in front of the instrument before starting the test.

**Command / Response:**

```json
{
    "commandId" : 606,
    "id" : 1234,
    "params" : {
    }
}
```

---


Cal check results are delivered via the same mechanism as a normal analysis test: applications should listen for the **ResultReceived** notification. The **ResultReceived** messages during a cal check will contain the following key / value pair:

```json
{
"calCheckResult" : {
    "errorCode" : 0,
    "expectedOffset" : -0.024661464078278187,
    "expectedRate" : 117000,
    "expectedResolution" : 141,
    "expectedSlope" : 0.020000619897627372,
    "offset" : -0.024702808306679813,
    "peak1" : 321.15657512473211,
    "peak2" : 873.30746403120543,
    "rate" : 130565.68490960269,
    "resolution" : 141.3370451726245,
    "slope" : 0.02000177890118493
}
}
```

---

<p id="GetMethodList"></p>

#### GetMethodList 

Used to get all available methods on the device. 
**Command:**
```json
{
  "commandId": 701,
  "id": 1234,
  "params": {}
}
```
**Response:**
```json
{
  "commandId": 701,
  "id": 1234,
  "params": {
    "methodList": [
      {
        "id": "alloy-C",
        "name": "Alloy"
      }
    ]
  }
}
```
---

<p id="GetCurrentMethod"></p>

#### GetCurrentMethod 

Used to get the currently selected method on the device. 
**Command:**
```json
{
  "commandId": 702,
  "id": 1234,
  "params": {}
}
```
**Response:**
```json
{
  "commandId": 702,
  "id": 1234,
  "params": {
    "methodList": [
      {    
        "id": "alloy-C",
        "name": "Alloy"
      }
    ]
  }
}
```

---

<p id="SetCurrentMethod"></p>

#### SetCurrentMethod 

Used to set the active method on the instrument. The only parameter ("methodId") contains the method to be set as active.
##### NOTE: DO NOT SET METHOD EVERY TEST. ONLY WHEN A METHOD CHANGE IS REQUIRED


**Command:**

```json
{
    "commandId" : 703,
    "id" : 1234,
    "params" : {
        "methodId" : "alloyPlus"
    }
}
```

**Response:**


none


---

<p id="SetTestInfoField"></p>

#### SetTestInfoField 

Used to set the value of a custom test information field (or "note") that will be attached to the next test that is run. The number of notes that can be attached to a test is unlimited. This command should be sent once for each note to be added to the test.

**Command:**

```json
{
    "commandId" : 604,
    "id" : 1234,
    "params" : {
        "fieldName": "sampleID",
        "fieldValue": "SS316"
    }
}
```

**Response:**

none

---

<p id="GetBeamConfiguration"></p>

#### GetBeamConfiguration 
Used to fetch the current beam settings from the current loaded method
```json
 {
    "commandId": 771,
    "id" : 1234,
    "params": {}
 }
```
Used to fetch a specific method beam settings from the method associated with
```json
 {
    "commandId": 771,
    "id" : 1234,
    "params": {
    	"methodId": "methodId"
	}
 }
```

---

<p id="SetBeamConfiguration"></p>

#### SetBeamConfiguration 

Used to set the duration of each **exposure**, in **seconds**.

**Command:**

```json
{
    "commandId" : 772,
    "id" : 1234,
    "params" : {
        "testEnd" : "maxTime",
        "beams" : [
            {
                "beam" : "Beam1",
                "min" : 0,
                "max" : 10
            },
            {
                "beam" : "Beam2",
                "min" : 0,
                "max" : 20
            }
        ]
    }
}
```
If the user wanted to change the **alloyPlusOptions**. 

```json
{
    "commandId" : 772,
    "id" : 1234,
    "params" : {
        "testEnd" : "maxTime",	
 	 "alloyPlusOptions" : {
	    "singleBeamNoLE" : false,
	    "singleBeamWithLE" : false,
	    "smartSort" : false,
	    "twoBeamsAlways" : true
	  },
        "beams" : [
            {
                "beam" : "Beam1",
                "min" : 0,
                "max" : 10
            },
            {
                "beam" : "Beam2",
                "min" : 0,
                "max" : 20
            }
        ]
    }
}
```
**Response:**

```json
{
    "commandId" : 772,
    "id" : 1234,
    "params" : {
    }
}
```

---

<p id="SetCloudSettings"></p>

#### SetCloudSettings

Used to enable or disable cloud connectivity.

**Command:**

To enable cloud connectivity
```json
{
    "commandId" : 778,
    "id" : 1234,
    "params" : {
        "enabled" : "true"
	}
}
```
To disable cloud connectivity
```json
{
    "commandId" : 778,
    "id" : 1234,
    "params" : {
        "enabled" : "false"
	}
}
```
**Response:**

```json
{
    "commandId" : 778,
    "id" : 1234,
    "params" : {
    }
}
```

---

<p id="GetUserFactorTemplateList"></p>

#### GetUserFactorTemplateList 

Used to fetch the list of available **user factor templates**. Each user **factor template** consists of the user-defined factor and offset to be applied to each element.

This API merely queries which **user factor templates** are **available** on the instrument. The templates themselves are defined by using the Vanta Desktop App or the Vanta instrument user interface.

**Command:**

```json
{
    "commandId": 750,
    "id": 1234,
    "params": {
    }
}
```

**Response:**

```json
{
    "commandId": 750,
    "id": 1234,
    "params": {
        "userFactorTemplateList": "None,model1,test"
    }
}
```

---

<p id="SetActiveUserFactor"></p>

#### SetActiveUserFactor 

Used to select which **user factor template** is to be used for the **next test**.

**Command:**

```json
{
    "commandId": 756,
    "id": 1234,
    "params": {
        "name": "model1"
    }
}
```

**Response:** None

---

<p id="GetActiveUserFactor"></p>

#### GetActiveUserFactor 

Used to query which user factor template has been selected to be used for the next test.

**Command:**

```json
{
    "commandId": 757,
    "id": 1234,
    "params": null
}
```

**Response:**

```json
{
    "commandId": 757,
    "id": 1234,
    "params": {
        "name": "model1"
    }
}
```

---

<p id="RemoveGradeLibrary"></p>

#### RemoveGradeLibrary

Removes the selected grade library from the list of available libraries.

**Command:**

```json
{
    "commandId": 709,
    "id": 1234,
    "params": {
        "xrfString": "gradelibrary"
    }
}
```

**Response:**

```json
{
    "commandId": 709,
    "id": 1234,
    "params": {}
}
```

---

<p id="GetGradeLibraryList"></p>

#### GetGradeLibraryList

Requests the list of available grade libraries.

**Command:**

```json
{
    "commandId": 722,
    "id": 1234,
    "params": {}
}
```

**Response:**

```json
{
    "commandId": 722,
    "id": 1234,
    "params": {
        "gradeLibraries": "ChinaExpanded,ChinaPower,Common,Compact,EN_DIN,JIS,QuickSort,Welding,barcodeGradeLib,gradeLib_Eskom,gradelibrary"
    }
}
```

---

<p id="GetGradeListByBase"></p>

#### GetGradeListByBase

Requests the list of recognized grades, sorted by base, of the currently selected grade library.

**Command:**

```json
{
    "commandId": 723,
    "id": 1234,
    "params": {}
}
```

**Response**

*Note*: This list is truncated for brevity, and is provided to show the structure of the response. Most instruments will return a much longer list.

```json
{
    "commandId": 723,
    "id": 1234,
    "params": {
        " None": [
            "None"
        ],
        "Aluminum": [
            "1000 Series",
            "1100",
            "1100-plus",
            "2007",
            "2011"
        ],
        "Cobalt": [
            "AlnicoVIII",
            "Cobalt",
            "Elgiloy",
            "F75",
            "FSX-414"
        ],
        "Copper": [
            "Be Cu",
            "C 110",
            "C 122",
            "C 151",
            "C 155"
        ],
        "Iron": [
            "1 1-4 Cr",
            "12L14",
            "2 1-4 Cr",
            "3310",
            "4130"
        ],
        "Magnesium": [
            "AZ31B",
            "AZ91Aor C"
        ],
        "Nickel": [
            "20Mo4",
            "Alloy 52",
            "Alloy 925",
            "Alloy D",
            "Waspaloy"
        ],
        "Niobium": [
            "Cb 103"
        ],
        "Pure": [
            "Ag",
            "Au",
            "Bi",
            "CP Ta",
            "Cr",
            "Zn"
        ],
        "Stainless": [
            "13-8 Mo",
            "14-4PH",
            "15-5 PH",
            "15-7 Mo",
            "Zeron100"
        ],
        "Tantalum": [
            "90Ta 10W",
            "97-3"
        ],
        "Tin": [
            "60Sn-40Pb",
            "63Sn-37Pb",
            "96-4",
            "B23 Babbitt",
            "SN 100C"
        ],
        "Titanium": [
            "Ti 10-3-2",
            "Ti 13-11-3",
            "Ti 15-3-3-3",
            "TiBetaC"
        ],
        "Tungsten": [
            "70W 30 Mo",
            "Densalloy",
            "Hevimet",
            "TungCarb S"
        ],
        "Zinc": [
            "90 Zn 10 Al"
        ],
        "Zirconium": [
            "Zr 2",
            "Zr 4",
            "Zr 702",
            "Zr 704",
            "Zr 705",
            "Zr CP"
        ]
    }
}
```

---

<p id="SetMethodDisplaySettings"></p>

#### SetMethodDisplaySettings 

Used to choose a number of settings that affect how results are displayed to the user.

The following options are supported:

- displaySigma: When displaying uncertainty, this parameter determines the number of standard deviations (sigmas) of uncertainty to display. Valid values are 1, 2 or 3.
- hideChemistry: When set to 1, the chemistry table will be omitted from the displayed result. Valid values are 0 or 1.
- showEstimatedLOD: When set to 1, causes non-detected elements to be included in the displayed chemistry table. Valid values are 0 or 1.
- showUncertainty: When set to 1, the chemistry table will include a column containing the estimated uncertainty for each element’s concentration.

**Command:**

```json
{
    "commandId": 738,
    "id": 1234,
    "params": {
        "displaySigma": 3,
        "hideChemistry": 0,
        "showEstimatedLOD": 0,
        "showUncertainty": 1
    }
}
```

**Response:** none

---

<p id="GetGradeMatchSettings"></p>

#### GetGradeMatchSettings

Requests the current user's grade match settings for the currently selected method.

**Command:**

```json
{
    "commandId": 744,
    "id": 1234,
    "params": null
}
```

**Response:**

```json
{
    "commandId": 744,
    "id": 1234,
    "params": {
        "gradeMatchOptions": {
            "forceLoad": false,
            "gradeCompare": {
                "grade": "316",
                "selected": "Best Match"
            },
            "gradeLibrary": [
                "gradelibrary"
            ],
            "gradeMatch": {
                "gradeMessage": true,
                "matchParams": {
                    "cutOff": 5,
                    "nSigma": 2
                },
                "nominalChemistry": true,
                "numberOfMatch": 3
            },
            "passFail": {
                "grade": "316",
                "matchParams": {
                    "cutOff": 1,
                    "nSigma": 2
                },
                "showMatchNumber": true
            },
            "trampLibrary": "Residuals (Tramp)"
        }
    }
}
```
---

<p id="SetGradeMatchSettings"></p>

#### SetGradeMatchSettings

Sets the current user's grade match settings for the currently selected method.

> Note: Since the expected parameter structure of this command is complex, it is recommended that clients first call GetGradeMatchSettings, and store the parameters included in the response from the instrument. The returned parameters can then be edited and passed as the parameters to SetGradeMatchSettings.

**Command:**
```json
{
    "commandId": 745,
    "id": 1234,
    "params": {
        "gradeMatchOptions": {
            "forceLoad": false,
            "gradeCompare": {
                "grade": "316",
                "selected": "Best Match"
            },
            "gradeLibrary": [
                "gradelibrary"
            ],
            "gradeMatch": {
                "gradeMessage": true,
                "matchParams": {
                    "cutOff": 5,
                    "nSigma": 2
                },
                "nominalChemistry": true,
                "numberOfMatch": 3
            },
            "passFail": {
                "grade": "316",
                "matchParams": {
                    "cutOff": 1,
                    "nSigma": 2
                },
                "showMatchNumber": true
            },
            "trampLibrary": "Residuals (Tramp)"
        }
    }
}
```

**Response:**

none


---

<p id="RefreshHardwareConfiguration"></p>

#### RefreshHardwareConfiguration 

Causes the instrument software to query the hardware for its configuration and notify the application when it is available.

> Note: The direct response to this command will be empty. The hardware configuration information will be returned as a HardwareConfigurationChanged notification.

**Command:**

```json
{
    "commandId": 211,
    "id":1234,
    "params":null
}
```
---

<p id="SetSystemTime"></p>

#### SetSystemTime

Sets the system time on the instrument.

> Note: This command will have no effect if the user has enabled "Automatic date & time" on the Date & Time settings page of the Vanta UI.

**Command:**

```json
{
    "commandId": 230,
    "id": 1234,
    "params": {
        "xrfString": "2021-09-02T16:05:00-04:00"
    }
}
```

**Response:**

```json
{
    "commandId": 230,
    "id": 1234,
    "params": {
        "systemTime": "Thu Sep 2 16:05:00 2021"
    }
}
```
---

<p id="PetWatchdog"></p>

#### PetWatchdog 

Signals to the instrument software that the connected client is still active and able to send commands.

> Note: When controlling Vanta instruments, this command must be sent at least once every four seconds during a test. Failure to do so will cause the x-ray tube to turn off and the test to end with the fault "Watchdog error". Best practice is to send the command immediately before or after StartTest, because if the unit has already not had a WD recently it can fail to start the test.  It is also recommended to set the time between these command to 1-2s so that if a send is delayed due to timing on the senders side, that the system does not give a WD fault.

**Command:**

```json
{
    "commandId": 244,
    "id": 1234,
    "params": null
}
```

**Response:** none

---

<p id="GetImage"></p>

#### GetImage

Fetches an image file from the instrument.

The file name to be fetched must match one of the filenames listed in the "images" array in a prior <a href="#ResultReceived">ResultReceived</a> notification.

The response includes the key "imageBuff", the content of which is a hex-encoded representation of the image in JPEG format. Decoding this string into binary and saving the resulting buffer to a file will result in a viewable JPEG image file.

> Note: The "imageBuff" key in the example response below has been truncated for brevity. In actual responses, this string is considerably longer.

**Command:**

```json
{
    "commandId": 115,
    "id": 1234,
    "params": {
        "xrfString": "2021-09-03/img-2021-09-03-3-1.jpeg"
    }
}
```

**Response:**

```json
{
    "commandId": 115,
    "id": 1234,
    "params": {
        "imageBuff": "ffd8ffe000104a46494600010100000100010000ffdb00430008060607060508...",
        "imageFileName": "2021-09-03/img-2021-09-03-3-1.jpeg",
        "testId": -1
    }
}
```

---

<p id="ImportGradeLibFromCsvV2"></p>

#### ImportGradeLibFromCsvV2

Imports a grade library from the contents of a comma-separated value (CSV) file. The name of the library is indicated by the `gradeLibraryName` parameter. The `buffer` parameter is used to pass the entire contents of the CSV file, not the file name.

*Note*: The `buffer` parameter in the example below is truncated for brevity. An actual grade library CSV is typically much larger.

**Command:**

```json
{
    "commandId": 832,
    "id": 1234,
    "params": {
        "gradeLibraryName": "gradelibrary",
        "buffer": "UNS #,Type Alloy,Beam,Grade Name,Version,Li Min,Li Max,Be Min,Be Max,B Min,B Max, ... Beam1,Beam2,SmartGrade,Message,NominalBase,Comment,Name,Reference,Source,BalanceElement,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
C 929,Copper,Any,C 929,7-Jul-15,0,0,0,0,0,0, ... 1,1,0,,Copper,,,,,Cu,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
A22010,Aluminum,Any,A201,7-Jul-15,0,0,0,0,0,0, ... 1,1,1,,Aluminum,,,,,Al,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
A02040,Aluminum,Any,204,7-Jul-15,0,0,0,0,0,0, ... 1,1,1,May mix w 206,Aluminum,,,,,Al,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
..."
    }
}
```

---

<p id="GetSDCardPercentOccupied"></p>

#### GetSDCardPercentOccupied

Requests the percentage of the SD card storage space that is currently used. In the response, `percent` is the percentange of the card that is occupied. `freeSpace` and `totalSpace` are the free space and total storage space, respectively, in bytes.

**Command:**

```json
{
    "commandId": 1003,
    "id": 1234,
    "params": {}
}
```

**Response:**

```json
{
    "commandId": 1003,
    "id": 1234,
    "params": {
        "freeSpace": 3612901376,
        "percent": 7.353287220001221,
        "totalSpace": 3899654144
    }
}
```

---

<p id="SetLoggerLevel"></p>

#### SetLoggerLevel

Sets the verbosity level of the selected log module. `logSource` denotes the log module name; possible module names include:

* Application
* API Manager
* Common
* Calc Engine
* Calc Manager
* Factory Manager
* HW Manager
* Login Manager
* Method Manager
* Power Manager
* Result Manager
* Settings Manager
* Test Manager
* Network Manager
* Unknown

`minLogLevel` sets the log level of the selected module. The log level is an integer from 0 (most verbose) to 4 (least verbose).

**Command:**

```json
{
    "commandId": 1005,
    "id": 1234,
    "params": {
        "logSource": "Test Manager",
        "minLogLevel": 2
    }
}
```

---

<p id="DeployLANConfig"></p>

#### DeployLANConfig

Activates a LAN configuration file. This configuration file must be present on the instrument's SD card, and be of the format described at https://github.com/aldebaran/connman/blob/master/doc/config-format.txt. The `xrfString` parameter denotes the name of the file, absent the ".config" extension. (In the example below, the file `my_local_network.config` would be used.)

*NOTE*: Use of this command with a misconfigured provisioning file can render the instrument unable to communicate. The provisioning file should be created by an IT professional, and must be compatible with local network specifications.

**Command:**

```json
{
    "commandId": 1348,
    "id": 1234,
    "params": {
        "xrfString": "my_local_network"
    }
}
```

**Response:**

none

---

<p id="ClearNetworkSettings"></p>

#### Clear Network Settings

Deletes any deployed network configuration files, resetting the network settings to the defaults.

**Command:**

```json
{
    "commandId": 1349,
    "id": 1234,
    "params": {}
}
```

**Response:**

none

---

<p id="Notifications"></p>

### Notifications 

---

<p id="SystemStatus"></p>

**SystemStatus** 

Sent by the instrument to inform the client of the instrument’s overall status. The systemStatus field contains the overall status, while the info field includes more detailed information (progress of an ongoing test, for example). The information in this notification is equivalent to what is displayed in the status bar at the bottom of the screen in the Vanta device application and PC software.

```json
{
    "commandId": 403,
    "id": 100,
    "params": {
        "systemStatus": "Ready",
        "info": ""
    }
}
```
---

<p id="BatteryStatus"></p>

**BatteryStatus**

Sent by the instrument periodically, or whenever a battery is inserted or removed.

The most useful keys are "mbRelStateOfCharge" and "dbRelStateOfCharge", which are the charge levels of the main battery and docking station battery, respectively, expressed as a percentage.

**Note:** This notification will not be sent if there are no batteries present.

```json
{
    "commandId": 403,
    "id": 103,
    "params": {
	"dbCurrent": "0",
	"dbCycleCount": "0",
	"dbDesignCapacity": "0",
	"dbManufactureDate": "0",
	"dbMaxCharge": "0",
	"dbMaxError": "0",
	"dbRelStateOfCharge": "0",
	"dbSerialNumber": "0",
	"dbStateOfCharge": "0",
	"dbTemperature": -273.1600036621094,
	"dbTemperatureInDeciK": "0",
	"dbTimeToEmpty": "0",
	"dbTimeToFull": "0",
	"dbVoltage": "0",
	"mbCurrent": "0",
	"mbCycleCount": "48",
	"mbDesignCapacity": "3400",
	"mbManufactureDate": "18190",
	"mbMaxCharge": "2916",
	"mbMaxError": "1",
	"mbRelStateOfCharge": "98",
	"mbSerialNumber": "819",
	"mbStateOfCharge": "2834",
	"mbTemperature": 19.639999389648438,
	"mbTemperatureInDeciK": "2928",
	"mbTimeToEmpty": "65535",
	"mbTimeToFull": "0",
	"mbVoltage": "16425",
	"scPercent": "100"
    }
}
```

---

<p id="ResultReceived"></p>

**ResultReceived**  
Sent by the instrument when a chemistry result is calculated during a test. Includes the following major sections:

- "analysis": Includes general information about the test, including which method was used, the date and time, whether or not the method is the final one of the test, location (if enabled), etc.
- "chemistry": The calculated chemistry for the test. Each item consists of the name of the element, its concentration, and the error.
Depending on the method that was used, the result object may include the following:
- "gradeMatch": Includes information on the alloy grade that was identified based on the chemistry.
- "images": Includes the filenames and other characteristics of the images associated with the test result.

**Example:**

```json
{
    "commandId" : 403,
    "id" : 206,
    "params" : {
        "result" : {
            "analysis" : {
                "auPlating" : "APNotApplicable",
                "collimated" : false,
                "compoundSuppress100Warning" : true,
                "compoundTemplateName" : "",
                "dailyId" : -1,
                "final" : false,
                "latitude" : null,
                "longitude" : null,
                "methodDispName" : "Alloy Plus",
                "methodFamilyName" : 1,
                "methodId" : "alloyPlus",
                "repeatTestIndex" : 1,
                "repeatTestTotal" : 1,
                "rohsActionLevel" : "NotApplicable",
                "rohsActionLevelName" : "",
                "rohsClassification" : "NotApplicable",
                "statusId" : 0,
                "testDateTime" : "2016-05-13 21:50:40.929",
                "testErrorInfo" : "",
                "testId" : -1,
                "testType" : "NORMAL",
                "tiTemplateName" : "",
                "tidName" : "",
                "userFactorName" : ""
            },
            "chemistry" : [{
                    "concentration" : 0,
                    "elementName" : "Ti",
                    "error" : 0.15532194077968597
                }, {
                    "concentration" : 0,
                    "elementName" : "V",
                    "error" : 0.24977830052375793
                }, {
                    "concentration" : 16.294563293457031,
                    "elementName" : "Cr",
                    "error" : 0.91738051176071167
                }, {
                    "concentration" : 2.6267390251159668,
                    "elementName" : "Mn",
                    "error" : 0.56923043727874756
                }, {
                    "concentration" : 67.481117248535156,
                    "elementName" : "Fe",
                    "error" : 1.3044502735137939
                }, {
                    "concentration" : 0,
                    "elementName" : "Co",
                    "error" : 0.52334719896316528
                }, {
                    "concentration" : 11.395604133605957,
                    "elementName" : "Ni",
                    "error" : 1.0371208190917969
                }, {
                    "concentration" : 0,
                    "elementName" : "Cu",
                    "error" : 0.083632573485374451
                }, {
                    "concentration" : 0,
                    "elementName" : "Zn",
                    "error" : 0.008038204163312912
                }, {
                    "concentration" : 0,
                    "elementName" : "Zr",
                    "error" : 0.018493751063942909
                }, {
                    "concentration" : 0,
                    "elementName" : "Nb",
                    "error" : 0.027878491207957268
                }, {
                    "concentration" : 2.2019779682159424,
                    "elementName" : "Mo",
                    "error" : 0.15944628417491913
                }, {
                    "concentration" : 0,
                    "elementName" : "Pd",
                    "error" : 0.083286717534065247
                }, {
                    "concentration" : 0,
                    "elementName" : "Ag",
                    "error" : 0.11914294958114624
                }, {
                    "concentration" : 0,
                    "elementName" : "Cd",
                    "error" : 0.17732831835746765
                }, {
                    "concentration" : 0,
                    "elementName" : "Sn",
                    "error" : 0.29287201166152954
                }, {
                    "concentration" : 0,
                    "elementName" : "Sb",
                    "error" : 0.24792744219303131
                }, {
                    "concentration" : 0,
                    "elementName" : "Hf",
                    "error" : 0.027575051411986351
                }, {
                    "concentration" : 0,
                    "elementName" : "Ta",
                    "error" : 0
                }, {
                    "concentration" : 0,
                    "elementName" : "W",
                    "error" : 0.20934316515922546
                }, {
                    "concentration" : 0,
                    "elementName" : "Re",
                    "error" : 0.026456462219357491
                }, {
                    "concentration" : 0,
                    "elementName" : "Pb",
                    "error" : 0.098546802997589111
                }, {
                    "concentration" : 0,
                    "elementName" : "Bi",
                    "error" : 0.0061364015564322472
                }, {
                    "concentration" : 0,
                    "elementName" : "LE",
                    "error" : 4.3033409118652344
                }
            ],
            "gradeMatch" : [{
                    "compGrade" : 1,
                    "gradeName" : "316",
                    "gradeSpec" : [{
                            "elementName" : "Cr",
                            "matchResult" : "InSpec",
                            "maxVal" : 18,
                            "minVal" : 16,
                            "testId" : -1
                        }, {
                            "elementName" : "Mn",
                            "matchResult" : "InSpec",
                            "maxVal" : 2,
                            "minVal" : 0,
                            "testId" : -1
                        }, {
                            "elementName" : "Fe",
                            "matchResult" : "InSpec",
                            "maxVal" : 72,
                            "minVal" : 61.279998779296875,
                            "testId" : -1
                        }, {
                            "elementName" : "Ni",
                            "matchResult" : "InSpec",
                            "maxVal" : 14,
                            "minVal" : 10,
                            "testId" : -1
                        }, {
                            "elementName" : "Cu",
                            "matchResult" : "NoSpec",
                            "maxVal" : 0.75,
                            "minVal" : 0,
                            "testId" : -1
                        }, {
                            "elementName" : "Mo",
                            "matchResult" : "InSpec",
                            "maxVal" : 2.9000000953674316,
                            "minVal" : 2,
                            "testId" : -1
                        }
                    ],
                    "matchMessage" : "aka CF8M",
                    "matchNumber" : 0,
                    "nominalFactor" : 1,
                    "passFailCutOff" : -1,
                    "passFailNSigma" : -1,
                    "passFailShowMatchNumber" : false,
                    "testId" : -1
                }, {
                    "compGrade" : 0,
                    "gradeName" : "317",
                    "gradeSpec" : [{
                            "elementName" : "Cr",
                            "matchResult" : "InSpec",
                            "maxVal" : 20,
                            "minVal" : 18,
                            "testId" : -1
                        }, {
                            "elementName" : "Mn",
                            "matchResult" : "InSpec",
                            "maxVal" : 2,
                            "minVal" : 0,
                            "testId" : -1
                        }, {
                            "elementName" : "Fe",
                            "matchResult" : "InSpec",
                            "maxVal" : 68,
                            "minVal" : 57.180000305175781,
                            "testId" : -1
                        }, {
                            "elementName" : "Ni",
                            "matchResult" : "InSpec",
                            "maxVal" : 15,
                            "minVal" : 11,
                            "testId" : -1
                        }, {
                            "elementName" : "Cu",
                            "matchResult" : "NoSpec",
                            "maxVal" : 0.75,
                            "minVal" : 0,
                            "testId" : -1
                        }, {
                            "elementName" : "Mo",
                            "matchResult" : "TooLow",
                            "maxVal" : 4,
                            "minVal" : 3,
                            "testId" : -1
                        }
                    ],
                    "matchMessage" : "aka CG8M",
                    "matchNumber" : 1.0118190050125122,
                    "nominalFactor" : 1,
                    "passFailCutOff" : -1,
                    "passFailNSigma" : -1,
                    "passFailShowMatchNumber" : false,
                    "testId" : -1
                }
            ],
            "images": [{
                    "collimatorSpotX": 0.5979166626930237,
                    "collimatorSpotY": 0.574999988079071,
                    "cropAreaHeight": 0,
                    "cropAreaLeft": 0,
                    "cropAreaTop": 0,
                    "cropAreaWidth": 0,
                    "fileName": "2021-09-03/img-2021-09-03-3-1.jpeg",
                    "imageHasCircle": true,
                    "imageType": 0
                }
            ],
            "testId" : -1,
            "testInfo" : {
                "info" : ""
            }
        }
    }
}
```
---

<p id="ExposureStatus"></p>

**ExposureStatus**  
Sent by the instrument to inform the client of the status of an ongoing test, including:

- the number of the current exposure
- the maximum expected number of exposures in the test
- the elapsed time in the current exposure
- the total expected time of the current exposure
- the index of the current repeat test (if enabled)
- the total number of expected repeat tests

```json
{
    "commandId": 403,
    "id": 207,
    "params": {
        "elapsedTime" : 4,
        "exposureNum" : 1,
        "maxExposures" : 2,
        "repeatTestNum" : 1,
        "totalRepeatTests" : 1,
        "totalTime" : 5
    }
}
```
---

<p id="HardwareConfigurationChanged"></p>

**HardwareConfigurationChanged**  
Sent by the instrument to inform the client that the hardware configuration has changed. Also sent in response to a RefreshHardwareConfiguration command.

```json
{
    "commandId" : 403,
    "id" : 131,
    "params" : {
        "detectorAssemblySerialNumber" : "",
        "detectorModel" : "XDET-10008",
        "detectorPreampSerialNumber" : "",
        "detectorSerialNumber" : "V26176",
        "detectorTempSet" : -15,
        "dockFirmwareVersion" : "0.0.0",
        "fanEnabled" : true,
        "fanPresent" : false,
        "filterCount" : "8",
        "filterWheelMotorPresent" : true,
        "filters" : [{
                "diameterInMicrons" : "0",
                "hasCollimator" : false,
                "materialAtomicNumber" : "74",
                "thicknessInMicrons" : "3000"
            }, {
                "diameterInMicrons" : "2718",
                "hasCollimator" : false,
                "materialAtomicNumber" : "13",
                "thicknessInMicrons" : "2000"
            }, {
                "diameterInMicrons" : "482",
                "hasCollimator" : false,
                "materialAtomicNumber" : "13",
                "thicknessInMicrons" : "2000"
            }, {
                "diameterInMicrons" : "2718",
                "hasCollimator" : false,
                "materialAtomicNumber" : "0",
                "thicknessInMicrons" : "0"
            }, {
                "diameterInMicrons" : "482",
                "hasCollimator" : false,
                "materialAtomicNumber" : "0",
                "thicknessInMicrons" : "0"
            }, {
                "diameterInMicrons" : "0",
                "hasCollimator" : false,
                "materialAtomicNumber" : "74",
                "thicknessInMicrons" : "3000"
            }, {
                "diameterInMicrons" : "482",
                "hasCollimator" : false,
                "materialAtomicNumber" : "29",
                "thicknessInMicrons" : "150"
            }, {
                "diameterInMicrons" : "2718",
                "hasCollimator" : false,
                "materialAtomicNumber" : "29",
                "thicknessInMicrons" : "150"
            }
        ],
        "fpgaDeviceType" : "",
        "fpgaDna" : "013af5c0ce84fb31",
        "fpgaFirmwareVersion" : "4.0.112",
        "fpgaGain" : 13896556,
        "fpgaMaxWidth" : "34",
        "fpgaPeakingTime" : "16",
        "fpgaPulseTime" : "11",
        "fpgaResetWidth" : "1",
        "fpgaSyncDelay" : "24",
        "fpgaThreshold" : "100",
        "hasAimingCamera" : false,
        "hasBluetooth" : false,
        "hasCollimation" : false,
        "hasGps" : false,
        "hasSDCard" : true,
        "hasSampleCamera" : false,
        "hasWifi" : true,
        "insModel" : "0",
        "insSerialNumber" : "800011",
        "k60FirmwareVersion" : "1.2.2",
        "powerPcbSerial" : "",
        "proximitySensorPresent" : true,
        "testStandFirmwareVersion" : "0.0.0",
        "tubeAnode" : "W",
        "tubeFirmware" : "39",
        "tubeHardware" : "6",
        "tubeMaxCurrent" : "200",
        "tubeMaxPower" : "4",
        "tubeMaxVoltage" : "40",
        "tubeMinCurrent" : "5",
        "tubeMinVoltage" : "5",
        "tubeModel" : "XTUB-10007",
        "tubeProtocol" : "3",
        "tubeSerialNumber" : "88175-00160",
        "tubeUsage" : 0,
        "xrfEngineSerialNumber" : ""
    }
}
```
---

<p id="DigitalIOStateChanged"></p>

**DigitalIOStateChanged**  
Sent by the instrument whenever the state of the external digital I/O changes. (Only sent by Vanta-iX instruments)

The digital I/O status is presented in the notification parameters as four separate 8-bit integers, one for each bank. The "bank4" parameter contains the content of the four user-defined digital inputs in the upper nibble. The individual bits in the nibble are arranged such that the uppermost bit corresponds to digital input 4.

Example: in the sample notification JSON below, "bank4" is set to 128, which is 80 in hexadecimal, or 1000 0000 in binary. This corresponds to digital input 4 being high, and the rest being low.

```json
{
	"commandId": 403,
	"id": 139,
	"params": {
		"bank1": 145,
		"bank2": 230,
		"bank3": 192,
		"bank4": 128
	}
}
```
---

<p id="TestStarted"></p>

**Test Started**  
Sent by the unit when a test starts. No params.
```json
{
	"commandId": 403,
	"id": 200,
	"params": {
	}
}
```
---

<p id="TestStopped"></p>

**Test Stopped**  
Sent by the unit when a test stops.
```json
{
  "commandId": 403,
  "id": 201,
  "params":
  {
    "stopReason": "Test Complete",
    "stopReasonInt": 0
  }
}
```
---

<p id="ExposureStarted"></p>

**Exposure Started**  
Sent by the unit when each beam of a test starts.
```json
{
  "commandId": 403,
  "id": 202,
  "params":
  {
    "exposureNum": 1,
    "maxExposures": 1
  }
}
```
---

<p id="ExposureStopped"></p>

**Exposure Stopped**  
Sent by the unit when each beam of a test stops.
```json
{
  "commandId": 403,
  "id": 203,
  "params":
  {
    "exposureNum": 1,
    "finalExposureStatus": "Time Elapsed",
    "maxExposures": 1
  }
}
```
---

<p id="SpectrumUpdate"></p>

**Spectrum Update**  
Sent by the unit when each the spectrum data is updated. The actual spectrum is in the data key. The energy scale for this data is found in the energyOffset and energySlope value which are in keV.
```json


{
  "commandId": 403,
  "id": 204,
  "params":
  {
    "spectrum":
    {
      "ambientPressure": 1024,
      "clipBottom": 0,
      "clipTop": 0,
      "colMultiplier": 1,
      "data": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 2, 6, 4, 13, 17, 25, 29, 22, 22, 27, 27, 25, 26, 40, 33, 35, 31, 38, 31, 30, 27, 31, 27, 34, 24, 31, 29, 24, 30, 23, 26, 17, 25, 34, 24, 15, 24, 18, 18, 31, 13, 9, 35, 35, 35, 28, 29, 26, 19, 15, 22, 16, 19, 11, 19, 22, 18, 14, 12, 16, 26, 20, 17, 22, 23, 17, 18, 23, 11, 21, 17, 20, 17, 26, 20, 14, 25, 24, 17, 18, 23, 26, 25, 27, 35, 32, 26, 34, 23, 30, 30, 28, 33, 28, 23, 22, 20, 17, 18, 21, 21, 14, 21, 12, 22, 13, 13, 18, 27, 19, 15, 25, 20, 12, 26, 25, 35, 29, 41, 27, 36, 24, 22, 18, 11, 18, 15, 17, 22, 18, 15, 21, 16, 22, 14, 14, 12, 16, 12, 14, 14, 13, 19, 12, 16, 12, 15, 19, 17, 25, 34, 48, 55, 85, 83, 75, 57, 37, 23, 29, 23, 19, 14, 17, 17, 14, 24, 19, 14, 15, 10, 11, 11, 19, 16, 19, 14, 22, 30, 23, 20, 27, 26, 33, 24, 14, 25, 20, 15, 11, 14, 18, 16, 22, 23, 16, 27, 28, 46, 48, 88, 119, 130, 144, 154, 110, 108, 47, 37, 29, 40, 20, 23, 35, 22, 36, 45, 42, 49, 42, 46, 31, 24, 29, 31, 33, 29, 37, 41, 41, 53, 70, 123, 233, 393, 880, 1749, 3334, 5432, 7743, 9442, 10367, 10273, 8578, 6270, 4221, 2391, 1185, 566, 224, 119, 84, 80, 71, 63, 63, 63, 104, 122, 209, 279, 467, 796, 1216, 1652, 2131, 2447, 2597, 2401, 2045, 1643, 1170, 687, 443, 232, 151, 96, 114, 95, 120, 195, 309, 606, 1428, 2966, 5416, 9844, 15880, 22477, 28750, 32272, 32733, 29566, 23880, 16808, 10949, 6195, 3340, 1543, 727, 333, 180, 100, 89, 82, 78, 79, 99, 97, 87, 108, 136, 165, 204, 260, 404, 602, 908, 1448, 2051, 3022, 4035, 4718, 5183, 5062, 4420, 3554, 2496, 1764, 1008, 576, 298, 142, 56, 56, 54, 113, 219, 432, 764, 1260, 1786, 2301, 2790, 2960, 2978, 2623, 2137, 1518, 1029, 583, 320, 174, 89, 51, 27, 21, 18, 17, 19, 14, 11, 13, 9, 16, 16, 30, 43, 57, 91, 109, 155, 170, 191, 174, 153, 152, 152, 164, 225, 292, 402, 433, 500, 480, 468, 407, 333, 261, 160, 104, 69, 43, 29, 16, 12, 11, 7, 8, 10, 2, 3, 4, 7, 2, 2, 11, 3, 6, 4, 7, 13, 16, 21, 20, 19, 36, 29, 27, 28, 16, 14, 8, 6, 2, 6, 6, 0, 3, 5, 9, 6, 4, 7, 4, 2, 6, 7, 8, 4, 5, 4, 1, 3, 10, 2, 10, 3, 9, 10, 7, 21, 13, 15, 16, 15, 18, 15, 10, 4, 3, 5, 6, 7, 7, 10, 6, 7, 9, 5, 6, 7, 9, 5, 2, 3, 5, 4, 3, 7, 3, 2, 6, 6, 6, 4, 4, 1, 0, 4, 9, 5, 7, 9, 4, 7, 15, 8, 11, 13, 11, 9, 4, 3, 5, 8, 12, 6, 5, 6, 7, 8, 12, 15, 4, 9, 12, 9, 8, 6, 4, 5, 4, 7, 6, 5, 7, 5, 3, 6, 5, 7, 5, 12, 13, 12, 9, 14, 11, 17, 9, 5, 6, 6, 7, 4, 8, 4, 2, 3, 9, 7, 9, 7, 24, 11, 23, 23, 26, 40, 54, 44, 54, 46, 41, 37, 15, 25, 24, 9, 13, 9, 3, 5, 3, 5, 5, 5, 4, 9, 7, 7, 10, 11, 11, 13, 11, 20, 16, 24, 18, 14, 24, 16, 15, 10, 19, 5, 10, 11, 13, 11, 11, 17, 21, 18, 30, 51, 59, 62, 59, 72, 75, 75, 55, 63, 42, 28, 31, 24, 10, 8, 11, 11, 5, 6, 8, 1, 6, 3, 10, 2, 5, 4, 8, 8, 12, 16, 22, 16, 24, 23, 26, 25, 36, 21, 32, 25, 20, 21, 8, 7, 9, 6, 5, 12, 13, 8, 13, 14, 15, 17, 18, 19, 24, 21, 17, 15, 26, 17, 17, 14, 5, 13, 13, 12, 8, 8, 10, 13, 8, 7, 7, 8, 11, 8, 10, 6, 7, 7, 3, 8, 9, 6, 10, 10, 16, 12, 11, 8, 6, 8, 12, 10, 11, 4, 14, 11, 9, 13, 10, 12, 4, 12, 12, 10, 10, 14, 10, 9, 11, 10, 10, 15, 12, 14, 7, 9, 12, 8, 14, 12, 12, 16, 15, 12, 10, 15, 12, 17, 11, 14, 8, 8, 16, 16, 19, 23, 15, 11, 11, 25, 18, 24, 17, 22, 24, 27, 27, 14, 27, 19, 19, 21, 18, 17, 15, 15, 24, 15, 12, 13, 26, 18, 19, 28, 22, 24, 33, 20, 21, 16, 26, 32, 25, 27, 28, 28, 35, 34, 32, 32, 35, 59, 56, 56, 45, 50, 74, 64, 64, 72, 64, 64, 59, 41, 39, 49, 42, 37, 42, 45, 31, 31, 29, 36, 40, 40, 34, 36, 42, 35, 46, 50, 56, 55, 82, 100, 152, 212, 315, 477, 674, 920, 1247, 1598, 2139, 2662, 3168, 3534, 4031, 4442, 4667, 4734, 4643, 4240, 4034, 3533, 3023, 2321, 1929, 1348, 1003, 655, 429, 293, 235, 148, 100, 59, 62, 38, 49, 36, 46, 44, 34, 42, 31, 56, 38, 26, 40, 44, 44, 38, 43, 45, 43, 43, 72, 43, 54, 53, 52, 57, 57, 52, 50, 52, 52, 71, 64, 58, 65, 72, 80, 67, 86, 87, 81, 88, 83, 96, 74, 104, 98, 95, 104, 105, 95, 110, 112, 103, 123, 97, 107, 92, 108, 106, 120, 107, 114, 98, 96, 104, 86, 107, 97, 79, 93, 88, 85, 79, 94, 94, 89, 83, 120, 107, 174, 198, 213, 330, 382, 512, 591, 698, 810, 811, 871, 885, 763, 819, 694, 584, 490, 395, 325, 241, 181, 163, 168, 148, 167, 166, 206, 209, 231, 231, 206, 226, 244, 234, 257, 266, 221, 226, 254, 251, 227, 216, 226, 193, 183, 155, 161, 137, 90, 75, 72, 59, 64, 45, 56, 48, 47, 46, 44, 39, 54, 49, 59, 55, 47, 57, 36, 53, 51, 45, 55, 54, 47, 49, 40, 59, 43, 54, 57, 60, 43, 63, 69, 62, 64, 54, 54, 54, 58, 65, 69, 74, 53, 75, 66, 63, 64, 64, 49, 63, 56, 45, 53, 66, 55, 41, 56, 61, 57, 44, 51, 54, 47, 44, 60, 52, 49, 62, 52, 47, 30, 53, 51, 45, 46, 58, 45, 54, 41, 41, 41, 47, 53, 47, 54, 48, 48, 46, 46, 41, 48, 51, 60, 62, 56, 32, 39, 54, 49, 34, 48, 45, 46, 37, 50, 49, 57, 67, 61, 63, 60, 60, 57, 59, 95, 91, 113, 81, 90, 93, 79, 76, 63, 85, 65, 55, 57, 59, 45, 50, 40, 73, 58, 53, 57, 53, 46, 51, 48, 60, 41, 47, 46, 43, 53, 30, 47, 34, 45, 44, 46, 45, 45, 38, 55, 38, 40, 45, 44, 39, 41, 57, 47, 43, 52, 36, 44, 54, 55, 53, 49, 55, 50, 50, 82, 55, 63, 67, 68, 70, 57, 64, 58, 40, 50, 45, 47, 36, 56, 44, 39, 32, 42, 41, 42, 48, 30, 49, 49, 40, 44, 48, 50, 43, 46, 56, 61, 43, 44, 43, 39, 46, 39, 42, 53, 33, 39, 45, 42, 38, 47, 42, 45, 47, 52, 44, 56, 50, 47, 47, 45, 47, 45, 59, 41, 62, 71, 66, 56, 61, 36, 50, 38, 52, 45, 43, 57, 57, 48, 39, 55, 39, 44, 44, 49, 48, 48, 48, 50, 42, 39, 45, 45, 48, 37, 32, 37, 37, 42, 46, 31, 39, 41, 38, 32, 36, 45, 48, 41, 54, 54, 31, 42, 36, 49, 48, 50, 31, 29, 46, 38, 34, 43, 37, 35, 37, 35, 43, 32, 47, 47, 33, 36, 42, 56, 43, 51, 49, 46, 46, 33, 40, 33, 48, 41, 47, 48, 39, 38, 43, 47, 43, 36, 43, 36, 41, 28, 47, 34, 35, 38, 30, 27, 39, 47, 51, 28, 44, 33, 39, 53, 43, 46, 50, 40, 42, 38, 35, 37, 32, 33, 32, 28, 39, 46, 34, 39, 38, 29, 47, 42, 39, 27, 45, 28, 29, 37, 44, 38, 31, 39, 29, 40, 30, 35, 33, 37, 38, 40, 37, 44, 35, 35, 39, 31, 39, 33, 29, 31, 25, 41, 28, 33, 33, 23, 38, 41, 33, 41, 35, 37, 31, 26, 29, 49, 40, 31, 45, 36, 34, 38, 37, 33, 37, 29, 38, 44, 46, 42, 37, 42, 40, 38, 38, 29, 38, 21, 30, 43, 33, 26, 32, 36, 29, 30, 46, 36, 26, 34, 32, 30, 24, 31, 35, 24, 32, 29, 35, 24, 43, 27, 25, 27, 37, 23, 34, 30, 29, 24, 27, 37, 27, 24, 20, 26, 33, 21, 28, 29, 30, 18, 28, 24, 31, 29, 39, 31, 29, 29, 21, 23, 32, 34, 41, 25, 29, 20, 25, 24, 21, 30, 21, 19, 21, 28, 28, 28, 26, 31, 30, 28, 33, 33, 33, 25, 33, 30, 25, 26, 25, 20, 20, 20, 35, 25, 29, 14, 19, 36, 28, 17, 16, 35, 28, 24, 22, 25, 19, 21, 23, 28, 40, 20, 21, 24, 25, 23, 27, 23, 27, 27, 13, 24, 27, 23, 29, 21, 30, 24, 21, 30, 16, 34, 31, 35, 20, 25, 23, 18, 19, 26, 23, 18, 30, 24, 22, 34, 21, 15, 28, 24, 19, 19, 20, 23, 18, 18, 31, 22, 26, 26, 18, 25, 19, 20, 30, 23, 19, 20, 16, 28, 26, 17, 23, 24, 18, 25, 18, 19, 17, 26, 20, 9, 26, 13, 21, 10, 16, 16, 18, 24, 20, 22, 22, 23, 21, 12, 19, 17, 15, 21, 23, 28, 19, 22, 20, 14, 13, 15, 16, 18, 11, 18, 18, 19, 15, 16, 18, 26, 10, 17, 15, 11, 16, 16, 14, 16, 18, 15, 16, 16, 18, 14, 14, 13, 15, 14, 18, 19, 18, 13, 11, 15, 17, 15, 16, 13, 11, 15, 12, 9, 13, 7, 21, 7, 10, 14, 11, 13, 9, 10, 8, 12, 12, 11, 16, 16, 13, 14, 9, 12, 17, 8, 12, 5, 14, 10, 16, 11, 12, 9, 9, 7, 8, 8, 11, 7, 9, 9, 13, 12, 10, 9, 5, 12, 13, 9, 7, 8, 9, 13, 7, 6, 7, 3, 7, 3, 10, 9, 10, 12, 4, 7, 8, 9, 7, 9, 5, 7, 3, 3, 5, 2, 1, 3, 4, 6, 5, 5, 10, 6, 5, 5, 4, 3, 11, 6, 2, 7, 4, 6, 4, 10, 3, 4, 2, 4, 5, 7, 3, 2, 6, 2, 6, 6, 4, 6, 5, 2, 2, 7, 9, 5, 5, 7, 5, 3, 3, 3, 2, 5, 2, 5, 5, 5, 4, 4, 2, 6, 3, 3, 5, 4, 5, 4, 4, 3, 4, 5, 8, 3, 1, 5, 4, 2, 2, 1, 3, 5, 4, 2, 3, 2, 5, 3, 5, 9, 2, 1, 8, 1, 3, 5, 3, 3, 3, 7, 4, 3, 2, 1, 1, 2, 3, 5, 4, 3, 5, 2, 5, 1, 3, 1, 4, 6, 1, 5, 7, 2, 2, 2, 2, 5, 4, 5, 3, 2, 4, 1, 0, 1, 4, 4, 6, 2, 1, 0, 1, 3, 2, 3, 3, 3, 3, 3, 4, 1, 0, 1, 3, 4, 3, 0, 2, 1, 1, 1, 3, 2, 0, 0, 0, 0, 1, 1, 1, 5, 1, 0, 1, 1, 1, 1, 2, 1, 0, 2, 1, 0, 1, 0, 0, 0, 1, 3, 2, 2, 0, 2, 1, 2, 3, 0, 3, 0, 0, 2, 2, 0, 2, 0, 5, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 0, 0, 1, 0, 2, 1, 0, 0, 1, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 2, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
      "detectorTemperature": -30.00041961669922,
      "energyOffset": -0.023466236257625495,
      "energySlope": 0.02000008493287967,
      "exposureNumber": 1,
      "fastCounts": 614270,
      "filter":
      {
        "diameterInMicrons": 2718,
        "hasCollimator": false,
        "materialAtomicNumber": 13,
        "thicknessInMicrons": 2000
      },
      "filterPosition": 0,
      "firstRate": 0,
      "inputCountRate": 124474.45828777355,
      "isFinal": false,
      "lastRate": 109723.42341539092,
      "liveTime": 4.350089226724404,
      "liveTimeFromHardware": 4.934908,
      "ltMultiplier": 1,
      "outputCountRate": 109723.42341539092,
      "pileups": 67016,
      "probeSerialNumber": 900000,
      "probeTemperature": 42,
      "realTime": 5,
      "resetCount": 35912,
      "resetTime": 0.065092,
      "slowCounts": 541475,
      "stepIndex": 1,
      "stepTotal": 3,
      "topResets": 38,
      "totalCounts": 541410,
      "totalExposureNumber": 0,
      "totalRate": 108282,
      "tubeCurrentMonitor": 29.65035057067871,
      "tubeCurrentSet": 29.597902297973633,
      "tubeVoltageMonitor": 39.98508071899414,
      "tubeVoltageSet": 39.99850845336914,
      "vacuumPressure": 1024,
      "widthRejects": 5779
    }
  }
}


```
---

<p id="ExposureStatus"></p>

**ExposureStatus**  
Sent by the unit when the exposure status changes
```json
{
  "commandId": 403,
  "id": 207,
  "params":
  {
    "elapsedTime": 5,
    "exposureNum": 1,
    "maxExposures": 1,
    "repeatTestNum": 1706,
    "totalRepeatTests": 99999,
    "totalTime": 5
  }
}
```
---

<p id="ErrorDuringTest"></p>

**ErrorDuringTest**  
Sent by the unit when there is an error to report during a test.
```json
{
	"commandId": 403,
	"id": 209,
	"params": {
		"TBD": "TBD"
	}
}
```
---

<p id="SettingsChanged"></p>

**Settings Changed**  
Sent by the unit when settings change
```json
{
	"commandId": 403,
	"id": 300,
	"params": {
		"TBD": "TBD"
	}
}
```
---

<p id="MethodLoaded"></p>

**Method Loaded**  
Sent by the unit when a new method is loaded
```json
{
	"commandId": 403,
	"id": 301,
	"params": {
		"TBD": "TBD"
	}
}
```
---

<p id="MethodLoading"></p>

**Method Loading**  
Sent by the unit when a new method is loading
```json
{
	"commandId": 403,
	"id": 302,
	"params": {
		"TBD": "TBD"
	}
}
```
---

<p id="NewLogMessages"></p>

**New Log Messages**  
Sent by the unit when there are new lines in the log file.  The messages are arranged as a list of strings, one per line.
```json
{
	"commandId": 403,
	"id": 701,
	"params":
	{
		"messages": [ "[2021/02/12 19:46:16.106] [DEBUG]    [API Manager]        [Xrf Dispatcher Thread]     "]
	}
}

```
---

<p id="TriggerPulled"></p>

**Trigger Pulled**  
Sent by the unit when the trigger is pulled  (Vanta Handheld) or start button is pressed (Vanta iX)
```json
{
	"commandId": 403,
	"id": 702,
	"params": {}
}
```


---
<p id="KeyPressed"></p>

**Key Pressed**  
Sent by the unit when one of the buttons on the unit is pressed. (Vanta Handheld)
```json
{
	"commandId": 403,
	"id": 704,
	"params": 
	{
		"keyActivated": 6
	}
}
```
If the value of keyActivated == 6 a key is depressed. If keyActivated == 7 a key is released.

---

<p id="BeamSettingsChanged"></p>

**Beam Settings Changed**  
Sent by the unit when the beam settings change.
```json
{
	"commandId": 403,
	"id": 771,
	"params": {
		"TBD": "TBD"
	}
}
```
<p id="SystemStatus"></p>

**System Status message**  
Sent by the unit when the system status changes. The systemStatus string is what typically appears at the bottom of the screen in device SW. It is recommeneded to show this string somewhere to users if applicable.
```json
{
	"commandId": 403,
	"id": 100,
	"params": 
    {
      "info": "", 
      "statusBits": 0, 
      "systemStatus": "Ready"
    }
}
```
<p id="DevicePluggedIntoAC"></p>

**DC Power is connected to unit**  
Sent by the unit when DC power is connected. Will be sent to new clients when the first connect if DC is connected.
```json
{
	"commandId": 403,
	"id": 110,
	"params": {
	}
}
```

<p id="DeviceDisconnectedFromAC"></p>

**DC Power is removed from unit**  
Sent by the unit when DC power is removed.
```json
{
	"commandId": 403,
	"id": 111,
	"params": {
	}
}
```

**OLYMPUS SCIENTIFIC SOLUTIONS AMERICAS**  
48 Woerd Avenue, Waltham, MA 02453 USA
Tel:  (781) 419-3900
