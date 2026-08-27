## v0.3.1 (2026-08-27)

### Fix

- paint the chat on the color of the theme itself
- paint the chat with the background of the theme

## v0.3.0 (2026-08-24)

### Feat

- paint the screen with the colors of the remote WeeChat
- copy from the chat, and paste more than one line
- watch the connection to the relay and take it up again

### Fix

- show what is selected in the chat, and copy it where it can be read
- keep the long links of the chat clickable
- wrap the input line like the input bar of WeeChat

## v0.2.0 (2026-08-13)

### Feat

- connect through a WebSocket, like the browser clients do
- display the session like WeeChat does
- connect to a relay and keep the session state
- decode the WeeChat relay protocol and its color codes

### Fix

- stop adding a second nick completer when completing a nick
- ask the buffer numbers again when WeeChat renumbers them

### Refactor

- rename the project to pywrc and install it with pipx
