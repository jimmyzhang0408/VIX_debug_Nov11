# Overview of the result object
Olympus XRF API


Last updated 22-March 2021 


## Introduction.
At the end of a test any websocket clients connected to the server will receive a final result object in json format.
This structure is quite large and can be intimidating the first time you try to interpret all of the information it contains.
So the aim of this document is to break down the information and show you that it is easy to navigate to the sections of interest
in the json depending on what it is you are looking for.

### Overview.

The result object is made up of multiple sections each containing logically common items.
The major sections are shown below in a simplified json object.
```json
{
  "analysis": {},
  "chemistry": [],
  "coating": [],
  "compoundResult": [],
  "exposureEnableFlags": [],
  "gradeMatch": [],
  "images": [],
  "pseudoElement": [],
  "regressionInfo": {},
  "spectra": [],
  "userFactorResult": []
}
```
The amount of data in the result object and the sections contained within it, depends on several factors. So any code that
interprets this data needs to be flexible and deal with variable length arrays, and the possibility that a specific item might not always be present.

### The 'analysis' object
This object contains some of the key information that you might be looking for during a test. Here are some of the most useful keys.
```json
  "final": true,                                This key will tell you if this is the last result.
  ...
  "methodDispName": "AlloyPlus",                This is the display name of the method used to generate this result
  "methodId": "alloyPlus-VMR",                  This is the internal name of the method file used. This will depend on the instrument type
  ...
  "testDateTime": "2021-01-19 17:46:10.054",    Date and time of the test in UTC time and ISO format.
  "testErrorInfo": "No error ",                 
  ...
  "testType": "NORMAL",                         Other option is CALCHECK       
  "tidName": "485",                             This is the daily test ID.  Increments automatically and resets at midnight local time.
```

### The 'chemistry' array
This is an array of chemistry results for all the elements in a method. If an element was not found it will still be in
this list but with a concentration of 0.The names of the elements use the standard symbols as defined by 
[IUPAC](https://iupac.org/what-we-do/periodic-table-of-elements/).  The error is 1-sigma and is used to represent our level of uncertainty on the concentration value.


```json
   "concentration": 0,                          This element was not found in the sample so concentration is 0.
   "elementName": "Ti",                         String defining the standard name of the element. 
   "error": 0.010170364752411842
```

> Note: In some methods an element "LE" can appear. This is our estimate of 'light elements Z<=11' that cannot be quantified.
> It is important to recognize that the number of elements in this array can vary depending on the method being used, or the number of beams in the measurement.
Any code processing this array ***should not*** assume a fixed number of elements.

### The 'processedChemistry' array
This is an array of chemistry results that have been post-processed in accordance with selected options such as user factors, 
pseudo-elements, element ordering, etc. The JSON format is identical to that described in the 'chemistry' section above. 

> Note: Since the ordering of the chemistry results in this array respects the element ordering settings configured on the
> instrument, the ordering will likely not match the ordering of the 'chemistry' array. Therefore, code processing this
> array ***should not*** assume that element _n_ of this array corresponds to element _n_ of the 'chemistry' array.

> Note: Since this array can include pseudo-element results, it is possible for its length to not match the length of the
> 'chemistry' array. Therefore, code processing this array ***should not*** assume that this array will have the same
> number of elements as the 'chemistry' array.

### The 'gradeMatch' array
This is an array of grades that have been found to match the sample. This array is only populated for Alloy modes, 
and even then might be empty if no matches were found.
Each  grade object in the gradeMatch array is broken down into a few sections shown below.
```json
  "gradeMatch": []
```
For each matching grade we have a grade object
```json
  "compGrade": 1,
  "gradeName": "316",                     This is the name given to the grade. This is most often a standard name, but is could be anthing that means something to the user.
  "gradeSpec": [],                        An array of elements in the spec.  See section below.
  "matchMessage": "",                     Optional message to show the user when this grade is found.
  "matchNSigma": 2,                       
  "matchNumber": 0,                       Match number.  A perfect match (all elements in spec) is zero.  Larger numbers means worse match.
  "nominalFactor": 1,
  "passFailCutOff": -1,                   If -1 pass fail not configured. If >=0 then this is the threshold for a pass.  If match <= threshold then pass.
  "passFailNSigma": -1,
  "passFailShowMatchNumber": false,
  "testId": -1
```

The grade spec is an array of elements. Where each element has the following information.

  Example 1.
```json
  "elementName": "V",                     Name of the element.
  "matchResult": "Tramp",                 Type of contribution.  Can be Tramp or Inspec.
  "maxVal": 0.15000000596046448,          Maximum allowed value of this element in the sample.
  "minVal": 0,                            Minimum allowed value of this element in the sample.
  "testId": -1
```        
  Example 2. 
```json
  "elementName": "Ni", 
  "matchResult": "InSpec",                This element is part of the spec and needs to be in the sample between the min and max values.
  "maxVal": 14,
  "minVal": 10,
  "testId": -1
```
Depending on the number of allowed matches, and the possible matching grades in the libraries, this array of grades could be any length including zero.

### Using the gradeMatch data to determine if a sample passed or failed.
One of the modes of operation for Alloy Mode is pass/fail, based on whether or not the sample matches the expected grade.  
The operator configures which grade that they want the Vanta to match and then if the sample matches the result will be a pass, otherwise it will show as a fail.
The gradeMatch object described above contains all the information needed to determine programatically the pass/fail status.

The following python code shows how to do this.
```python

on_test_complete(result_json, io_state):
    output_result = 0                           # Set the default result to be zero.  All Customer outputs off.
    result = json.loads(result_json)            # Load the result_json into the result json object.
    grades=result["gradeMatch"]                 # Find the gradeMatch section of the results.
    for g in grades:                            # Loop around looking at each grade.
        cutoff =float(g['passFailCutOff'])      # Find the passFailCutOff
        if cutoff >= 0:                         # Not the grade we want if "-1". Any grade we are trying to match will show here with a cutoff of zero or greater. Not selected grades will be -1.
            match_num= float(g['matchNumber'])  # and match num
            if match_num <= cutoff:              # Then we have an acceptable match and hence a pass
                output_result = 12              # enable bits 2,3   b1100
                message = "Found Passing grade in file '" + str(g['gradeName']) + "'. Output set to -> "+str(output_result)
            else:
                output_result = 3               # enable bits 0,1   b0011
                message = "Found failing grade in file '" + str(g['gradeName']) + "'. Output set to -> "+str(output_result)
    states = list(io_state)
    states[3] = output_result                   # Update the state of the GPIO pins with the result. Only the 4 LSB's are used.
    io_state = tuple(states)
    return (result_json, io_state, message)
```
>Note only 1 grade in the grade list will have a passFailCutOff that is not -1.
> 
First read the passFailCutOff from the grade.  If this number is >=0 then this is the grade we are trying to match. If the matchNumber for that grade is <= passFailCutOff
then we have a pass. Otherwise a fail.


### The 'spectra' array
The spectra section of the result is complex enough that it deserves it's [own document](spectrum_file_structure.md).
It is also worth noting that single spectra are sent during a test using the [notification id =204](API-Command-List.md)
