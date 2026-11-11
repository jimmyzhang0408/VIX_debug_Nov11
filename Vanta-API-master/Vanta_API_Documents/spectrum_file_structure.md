# Overview of the spectra object
Olympus XRF API

Last updated 22-March 2021 


## Introduction.
During a test any websocket clients connected to the server will receive updates to the spectra object in json format. 
These will be sent as a [notification with ID 204](API-Command-List.md). Spectra will also be part of the result object sent 
as a [notification with ID 206](API-Command-List.md).  You can find more about the result object [here](results_file_structure.md).

This object is quite large and can be intimidating the first time you try to interpret all of the information it contains.
So the aim of this document is to break down the information, and show that it is easy to navigate to the sections of interest
in the json depending on what it is you are looking for.

### Overview.

The spectra object is essentially an array of spectra.  Each spectra represents one "exposure" or "beam" of the analysis. 
For some methods we are able to detect all the elements of interest in a single beam, so the spectra array only has one item.
For more complex methods like 2-beam alloy, or 3-beam Geochem there with be more items.

So the spectra section of a results file will looks something like this
```json

  "spectra": []     This array will usually contain one or more spectra. 

```
>Note In the event that a test did not start due to a fault, then it is possible for this to be empty.
> 
Each item in the array will looks something like the one shown below. This example is from a 10s exposure
```json

    "ambientPressure": 1013,                        Air pressure in mBar measured by internal barometer.
    "clipBottom": 0,
    "clipTop": 0,
    "colMultiplier": 1,
    "data": [],                                     This is the spectrum data. An array of up 2048 integers. Not shown for clarity here.
    "detectorTemperature": -29.999191284179688,     Detector temperature monitored during the test.
    "energyOffset": -0.023466236257625495,          Energy offset of the first bin of the spectum. Units are keV. So in this example that is -23.4 eV
    "energySlope": 0.02000008493287967,             Step size in energy between bins in the spectrum. Units are keV. Typically very close to  20.00 eV
    "exposureNumber": 1,                            The number of the exposure.  Can be 1,2 or 3.
    "fastCounts": 1235097,                          Total number of x-rays detected during the test.  Not every events is used in the spectrum.
    "filter": {},                                   Filter object describing the position, thickness and material used for this exposure.
    "filterPosition": 0,
    "firstRate": 0,
    "inputCountRate": 125145.2863195534,            Average rate during the livetime of the test.
    "isFinal": true,                                Set to false if this is one of the intermediate spectra sent during an exposure.
    "lastRate": 110250.01253887685,
    "liveTime": 8.694622322582761,                  The amount of time that the system was able to dedicate to processing x-ray events.
    "liveTimeFromHardware": 9.869305,               
    "ltMultiplier": 1,
    "outputCountRate": 110250.01253887685,          Effective countrate 
    "pileups": 135639,                              Total number of times that x-rays events that were rejected.
    "probeSerialNumber": 900000,                    SN of the analyzer
    "probeTemperature": 38,                         Internal temperature of the probe head. Used in combination with the pressure to correct for air density.
    "realTime": 10,                                 Elapsed "wall time" of the test.
    "resetCount": 72107,
    "resetTime": 0.130695,
    "slowCounts": 1088091,                         
    "stepIndex": 1,
    "stepTotal": 3,
    "topResets": 67,
    "totalCounts": 1087955,
    "totalExposureNumber": 1,
    "totalRate": 108795.5,
    "tubeCurrentMonitor": 29.65035057067871,        Monitored tube current during the test in uA
    "tubeCurrentSet": 29.597902297973633,
    "tubeVoltageMonitor": 39.98508071899414,        Monitored tube voltage during the test in kV
    "tubeVoltageSet": 39.99850845336914,
    "vacuumPressure": 1013,
    "widthRejects": 11367

```

### How the plot the spectrum.
If you intend to display the spectrum in your software then you will need to calculate the x-axis (energy scale) for your plot using the simple formula 

>Energy = mx + c   

Where x is the bin number indexed from zero.   m is the value ***"energySlope"*** and c is the value ***"energyOffset"***

So using the example above the energy of the first spectrum bin in the array data[] is -0.023466236257625495 keV  or -23.46eV

>Note.  If the tubeVoltage is lower than 40keV then the number of bins will be reduced. For example at 20keV there would be ~1000 bins. 
> So any software needs to consider the size of the dataset and not assume a fixed number each time.
> Do not assume the energyOffset or energySlope are fixed quantities either.
