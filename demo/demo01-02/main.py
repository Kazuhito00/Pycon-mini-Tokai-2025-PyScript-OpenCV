from pyscript import display
from datetime import datetime

now = datetime.now()

display("Hello World: " + now.strftime("%Y/%m/%d %H:%M:%S"))
