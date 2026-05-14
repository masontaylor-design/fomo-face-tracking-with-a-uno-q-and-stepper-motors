# fomo-face-tracking-with-a-uno-q-and-stepper-motors
This is a project of fomo facetracking with a arduino uno q, 2 stepper motors,s and a phone stream to the Uno Q 
To do this project, you will need a couple of  things 
a phone with a hotspot
2 a4988 drivers
2 100uf capacitors
a bunch of jumper wires and a breadboard 
a 3d printer or the ability to fabricate a mount for the steppers and phone
An Arduino Uno Q
2 stepper motors

<img width="1472" height="1640" alt="image" src="https://github.com/user-attachments/assets/c657d3f8-92a9-4a90-9b54-cb3ca49cc21f" />

The first thing that you need to do is to wire the stepper motors, make sure the long leg of the capacitor is on the VMOT, and follow the directions in the picture above. connect sleep reset to 3v3 and ms1, ms2, ms3 to 3v3 for 1/16th step for 1/8 gnd 3v3 gnd for 1/4 its 3v3 gnd gnd and for 1 step its gnd gnd gnd. For the stepper wires, I had b1 black, a1 green, b2 blue, and a2 red, but this seems to vary across different steppers, so ideally, you would check with a multimeter to see which wires correspond to which coils. 
The code is made for arduino app lab, so that is what you should probably use 
to use the face stream. You will need to follow the instructions in the Python output. You will need to use Safari for everything. (You need to download something to get the cam to work.)
I added the file with my design for the steppers and phone frame. Please double-check the dimensions before printing. 


I am having an issue with the upper stepper motor not bringing the phone back up after it appears to be too far down. The biggest cause of the problem is the stepper's current draw being too low due to the driver type.



All credit to Claude for basically writing all of the code, and https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet for the model that is being used to track to do the tracking of the face
