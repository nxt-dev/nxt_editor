#!/usr/bin/python
#
# Open or reference 'sub_graphs' graph in Maya or Standalone and pass an nxt
# graph, mayapy.exe path and parameters in the '_maya_sub_graph' node, and
# this will run that graph in maya standalone
#
# Shell Example:
# open a shell. Navigate to your bin/mayapy.exe file in your installation of
# maya. Then run: mayapy.exe path/to/this/run_maya_graph.py -g path/to/nxt_graph/you_want_to_run.nxt
#

# command line arguments
import argparse
import json
import os


# define the function for the dictionary argument
def dict_or_string(value={}):
    """This will ensure the data being passed to the argparse for parameters
    is always a dictionary. We expect a json string, a dictionary, or a path to
    a json file

    :param value: The parameters you want to pass to the graph, defaults to {}
    :type value: dict | str, optional
    :raises TypeError: Error if it's not a str that is json or dict
    :return: Return the dictionary of the data being passed as str or dict
    :rtype: dict
    """
    # check see if it's a dictionary.
    if isinstance(value, dict):
        return value
    try:
        # Try parsing as a dictionary
        parsed_dict = json.loads(value)
        if isinstance(parsed_dict, dict):
            return parsed_dict
    except ValueError:
        pass
    # Check if value string is a valid parameters file
    if os.path.isfile(value):
        try:
            # open the filepath and load the json file
            with open(value, "r") as fp:
                return json.load(fp)
        except json.JSONDecodeError:
            pass
    raise TypeError(
        "Passed value must be of type dict, string of a dict, or filepath to parameters file!"
    )


# Initialize parser
parser = argparse.ArgumentParser(
    description="This is a cli for running the standalone maya"
)

# Adding optional argument
parser.add_argument(
    "-g",
    "--graph_path",
    help="The path to the nxt graph you want to run.",
    required=True,
)
parser.add_argument(
    "-p",
    "--parameters",
    help="""The parameters you want to pass to the graph. Parameters are a string representing a 
    dictionary.e.g. {'path/to/node.attr':'value'}""",
    type=dict_or_string,
),
parser.add_argument(
    "-s",
    "--start_node",
    help="The path to the nxt node init the graph you want to run.",
)

# Read arguments from command line
args = parser.parse_args()


if __name__ == "__main__":
    # import maya standalone
    from maya import standalone

    # initialize maya standalone
    standalone.initialize()

    # in maya import the execute graph for nxt
    from nxt import execute_graph

    #  make sure you can evaluate the start node
    start_node = None
    if args.start_node:
        if isinstance(args.start_node, str):
            start_node = args.start_node

    # execute the graph
    execute_graph(args.graph_path, parameters=args.parameters, start=start_node)
    # uninitialize maya standalone
    standalone.uninitialize()
