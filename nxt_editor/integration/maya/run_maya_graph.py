#!/usr/bin/python
#
# Open or reference "sub_graphs" graph in Maya or Standalone and pass an nxt
# graph, mayapy.exe path and parameters in the "_maya_sub_graph" node, and
# this will run that graph in maya standalone
#
# Shell Example:
# open a shell. Navigate to your bin/mayapy.exe file in your installation of
# maya. The run: mayapy.exe path/to/this/run_maya_graph.py -g path/to/nxt_graph/you_want_to_run.nxt
#

# command line arguments
import argparse

# Initialize parser
parser = argparse.ArgumentParser(description="This is a cli for running the standalone maya")

# Adding optional argument
parser.add_argument("-g", "--graph_path", help="The path to the nxt graph you want to run.")
parser.add_argument(
    "-p",
    "--parameters",
    help="""The parameters you want to pass to the graph. Parameters are a string representing a 
    dictionary.e.g. {'path/to/node.attr':'value'}""",
),
parser.add_argument("-s", "--start_node", help="The path to the nxt nofe inI the graph you want to run.")

# Read arguments from command line
args = parser.parse_args()


if __name__ == "__main__":
    if args.graph_path:
        # import maya standalone
        from maya import standalone

        # initialize maya standalone
        standalone.initialize()

        # in maya import the execute graph for nxt
        from nxt import execute_graph

        # make sure you can evaluate the parameters as a dict since it's passed as a string
        parameters = {}
        #  make sure you can evaluate the start node
        start_node =  None
        # if there are parameters passed. We make sure they get passed to the graph
        if args.parameters:
            if isinstance(args.parameters, str):
                parameters = eval(args.parameters)
        if args.start_node:
            if isinstance(args.start_node, str):
                start_node = args.start_node
                
        # execute the graph
        execute_graph(args.graph_path, parameters=parameters, start=start_node)
        # uninitialize maya standalone
        standalone.uninitialize()
