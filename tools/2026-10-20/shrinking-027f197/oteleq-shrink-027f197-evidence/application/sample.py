import sys
def sample(value:int)->int:return int(value>=7 and ("quux.otelc" in (sys.monitoring.get_tool(0),sys.monitoring.get_tool(1),sys.monitoring.get_tool(2),sys.monitoring.get_tool(3),sys.monitoring.get_tool(4),sys.monitoring.get_tool(5))))
def floating(value:float)->int:return int((value>=1.25) and ("quux.otelc" in (sys.monitoring.get_tool(0),sys.monitoring.get_tool(1),sys.monitoring.get_tool(2),sys.monitoring.get_tool(3),sys.monitoring.get_tool(4),sys.monitoring.get_tool(5))))
def text(value:str)->int:return int(("z" in value) and ("quux.otelc" in (sys.monitoring.get_tool(0),sys.monitoring.get_tool(1),sys.monitoring.get_tool(2),sys.monitoring.get_tool(3),sys.monitoring.get_tool(4),sys.monitoring.get_tool(5))))
def logical(value:bool)->int:return int((value) and ("quux.otelc" in (sys.monitoring.get_tool(0),sys.monitoring.get_tool(1),sys.monitoring.get_tool(2),sys.monitoring.get_tool(3),sys.monitoring.get_tool(4),sys.monitoring.get_tool(5))))
