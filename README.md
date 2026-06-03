# TTYDR_Cam_Tool
A python script to extract and pack .cam.zst files for TTYD Remake<br> 
The tool is currently in the testing phase and is not yet fully developed.

# How to use it
First you need to have pyhton installed, and then you need to run that command <br>
`pip install zstandard`<br> 
after that place the .py in the same folder as the .cam.zst files, <br> 
Then run this command to extract a file <br> 
`python cam_tool.py extract "D:\YOUR_PATH\gor_01.cam.zst"`<br> 
and then to pack it use<br> 
`python cam_tool.py pack "D:\YOUR_PATH\gor_01.cam.json"`<br> 
the .cam.zst must be in the same folder as the json.

# AI
I heard that the community needs a tool to extract the cam files. 
I’m not very experienced with this, so I used AI to help me. 
I think it’s better to have a tool that had AI use for helping than to have none tool at all. 
