## Unreleased

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
