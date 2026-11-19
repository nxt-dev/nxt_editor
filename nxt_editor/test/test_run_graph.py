"""Running a graph headless, in Maya, Blender or Unreal.

Every host's runner takes the same arguments: the graph, a node to start
from and parameters as JSON or a JSON file. It exits 0 when the graph ran
and 1 when it failed, so a farm or a script can tell. Blender leaves the
runner the arguments after ``--``. Unreal splits ``-script`` at spaces, so
its runner also reads them from NXT_RUN_GRAPH_ARGS, which the
``/_unreal_headless_graph`` node sets. The builtin launch nodes build the
command for each host.

No host is started here: the runners are loaded by path, as the hosts load
them, and the launch nodes run with subprocess replaced.
"""
# Built-in
import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# Internal
from nxt.session import Session

INTEGRATION = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'integration')
RUNNERS = {
    'shared': os.path.join(INTEGRATION, 'run_graph.py'),
    'maya': os.path.join(INTEGRATION, 'maya', 'run_maya_graph.py'),
    'blender': os.path.join(INTEGRATION, 'blender', 'run_blender_graph.py'),
    'unreal': os.path.join(INTEGRATION, 'unreal', 'Content', 'Python',
                           'run_unreal_graph.py'),
}


def load(name):
    spec = importlib.util.spec_from_file_location(
        'test_runner_' + name, RUNNERS[name])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, data):
    with open(path, 'w') as fp:
        json.dump(data, fp)
    return path


class GraphCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_run_graph_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, 'out.txt').replace(os.sep, '/')
        self.ok = write(os.path.join(self.tmp, 'ok.nxt'), {
            'version': '1.17', 'alias': 'ok',
            'nodes': {
                '/': {'attrs': {'out': {'type': 'raw', 'value': ''},
                                'word': {'type': 'raw', 'value': 'default'}}},
                '/first': {'start_point': True, 'code': [
                    "open('${out}', 'a').write('first ${word};')"]},
                '/second': {'execute_in': '/first', 'code': [
                    "open('${out}', 'a').write('second;')"]},
            }})
        self.bad = write(os.path.join(self.tmp, 'bad.nxt'), {
            'version': '1.17', 'alias': 'bad',
            'nodes': {'/boom': {'start_point': True, 'code': [
                "raise RuntimeError('on purpose')"]}}})
        self.shared = load('shared')

    def written(self):
        with open(self.out) as fp:
            return fp.read()

    def main(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return self.shared.main('Test', list(argv))


class Arguments(GraphCase):

    def test_parameters_can_be_json_or_a_json_file(self):
        parse = self.shared.dict_or_string
        self.assertEqual({'/.a': 1}, parse('{"/.a": 1}'))
        path = write(os.path.join(self.tmp, 'p.json'), {'/.b': 2})
        self.assertEqual({'/.b': 2}, parse(path))
        self.assertEqual({'/.c': 3}, parse({'/.c': 3}))

    def test_anything_else_is_refused_before_a_graph_runs(self):
        parse = self.shared.dict_or_string
        for bad in ('not json', '[1, 2]', os.path.join(self.tmp, 'none')):
            with self.assertRaises(argparse.ArgumentTypeError):
                parse(bad)
        with mock.patch('sys.stderr'), self.assertRaises(SystemExit):
            self.shared.make_parser('Test').parse_args(
                ['-g', self.ok, '-p', 'not json'])

    def test_a_graph_is_required(self):
        with mock.patch('sys.stderr'), self.assertRaises(SystemExit):
            self.shared.make_parser('Test').parse_args([])

    def test_a_parameters_file_can_be_in_any_language(self):
        # With a byte order mark too, as Windows tools often write one.
        path = os.path.join(self.tmp, u'参数.json')
        with open(path, 'wb') as fp:
            fp.write(u'﻿{"/.名": "Привет"}'
                     .encode('utf-8'))
        self.assertEqual({u'/.名': u'Привет'},
                         self.shared.dict_or_string(path))

    def test_the_help_names_the_runner_not_the_host(self):
        parser = self.shared.make_parser('Blender', 'run_blender_graph.py')
        self.assertIn('run_blender_graph.py', parser.format_usage())
        self.assertIn('Blender', parser.description)


class Running(GraphCase):

    def test_a_graph_that_runs_exits_0(self):
        code = self.main('-g', self.ok, '-p', json.dumps({'/.out': self.out}))
        self.assertEqual(0, code)
        self.assertEqual('first default;second;', self.written())

    def test_parameters_are_set_before_it_runs(self):
        self.main('-g', self.ok, '-p',
                  json.dumps({'/.out': self.out, '/.word': 'given'}))
        self.assertEqual('first given;second;', self.written())

    def test_it_can_start_from_a_node(self):
        self.main('-g', self.ok, '-s', '/second', '-p',
                  json.dumps({'/.out': self.out}))
        self.assertEqual('second;', self.written())

    def test_a_graph_that_fails_exits_1(self):
        self.assertEqual(1, self.main('-g', self.bad))

    def test_a_missing_graph_exits_1(self):
        self.assertEqual(1, self.main('-g', os.path.join(self.tmp, 'no.nxt')))


class Hosts(GraphCase):

    def test_blender_hands_on_only_what_follows_the_double_dash(self):
        blender = load('blender')
        argv = ['blender', '--background', 'scene.blend', '--python', 'x.py',
                '--', '-g', 'graph.nxt', '-s', '/a']
        self.assertEqual(['-g', 'graph.nxt', '-s', '/a'],
                         blender.runner_args(argv))
        self.assertEqual([], blender.runner_args(['blender', '-b']))

    def test_unreal_reads_its_arguments_from_the_environment(self):
        unreal = load('unreal')
        args = ['-g', self.ok, '-p', json.dumps({'/.out': self.out})]
        env = {unreal.ARGS_ENV: json.dumps(args)}
        with mock.patch.dict(os.environ, env), mock.patch('sys.stdout'):
            self.assertEqual(0, unreal.main([]))
        self.assertEqual('first default;second;', self.written())

    def test_maya_and_blender_also_read_the_environment(self):
        # mayapy turns characters outside the system's code page into ?, so
        # a graph in a folder named in Chinese has to come this way.
        args = ['-g', self.ok, '-p', json.dumps({'/.out': self.out})]
        env = {self.shared.ARGS_ENV: json.dumps(args)}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(args, self.shared.runner_argv([]))
            # A command line that has arguments wins.
            self.assertEqual(['-g', 'x'], self.shared.runner_argv(['-g', 'x']))
            blender = load('blender')
            parsed = []
            with mock.patch.object(blender, '_run_graph',
                                   return_value=self.shared),                     mock.patch.object(self.shared, 'run', parsed.append):
                blender.main(['blender', '--background'])
            self.assertEqual(self.ok, parsed[0].graph_path)

    def test_each_runner_finds_the_shared_arguments(self):
        # Every runner loads run_graph.py beside it by path, the way a
        # host without Qt has to.
        self.assertTrue(os.path.isfile(load('unreal')._run_graph_path()))
        for name in ('maya', 'blender'):
            module = load(name)
            self.assertEqual('Run an nxt graph in {} without its UI.'.format(
                name.title()),
                module._run_graph().make_parser(name.title()).description)


class LaunchNodes(GraphCase):
    """The builtin nodes that start a host from inside another graph."""

    def launch(self, node, attrs):
        # The nodes ship with nxt core, which can be a release behind the
        # editor while both are being updated.
        import nxt
        builtins = os.path.join(os.path.dirname(nxt.__file__), 'builtin',
                                'sub_graphs.nxt')
        with open(builtins, encoding='utf-8') as handle:
            if '"{}"'.format(node) not in handle.read():
                self.skipTest('this nxt core has no {} node'.format(node))
        graph = write(os.path.join(self.tmp, 'launch.nxt'), {
            'version': '1.17', 'alias': 'launch',
            'references': ['$NXT_BUILTINS/sub_graphs.nxt'],
            'nodes': {'/run': {'instance': node, 'start_point': True,
                               'attrs': {k: {'value': v}
                                         for k, v in attrs.items()}}}})
        with mock.patch('subprocess.Popen') as popen:
            Session().execute_graph(graph)
        self.assertEqual(1, popen.call_count)
        return popen.call_args

    def test_blender_runs_the_graph_in_the_background(self):
        call = self.launch('/_blender_background_graph', {
            '_graph_path': repr(self.ok), '_blender_version': '5.1',
            '_blend_file': repr('C:/scenes/shot.blend'),
            '_start_node': repr('/second'),
            '_parameters': repr({'/.word': 'x'})})
        command = call.args[0]
        # The default install path is a Windows one.
        expected = ('Blender 5.1/blender.exe' if sys.platform == 'win32'
                    else '/blender.exe')
        self.assertTrue(command[0].endswith(expected), command[0])
        self.assertEqual(['--background', 'C:/scenes/shot.blend',
                          '--python'], command[1:4])
        self.assertTrue(command[4].replace(os.sep, '/').endswith(
            'integration/blender/run_blender_graph.py'))
        self.assertEqual(['--', '-g', self.ok, '-p', '{"/.word": "x"}',
                          '-s', '/second'], command[5:])

    def test_unreal_passes_the_arguments_in_the_environment(self):
        call = self.launch('/_unreal_headless_graph', {
            '_graph_path': repr('C:/my graphs/build.nxt'),
            '_project': repr('C:/proj/Game.uproject'),
            '_unreal_version': '5.4'})
        command = call.args[0]
        expected = '/Engine/Binaries/Win64/UnrealEditor-Cmd.exe'
        if sys.platform == 'win32':
            expected = 'UE_5.4' + expected
        self.assertTrue(command[0].endswith(expected), command[0])
        self.assertEqual(['C:/proj/Game.uproject', '-run=pythonscript',
                          '-script=run_unreal_graph.py', '-unattended',
                          '-nosplash', '-nullrhi'], command[1:])
        args = json.loads(call.kwargs['env']['NXT_RUN_GRAPH_ARGS'])
        # A path with a space in it arrives whole.
        self.assertEqual(['-g', 'C:/my graphs/build.nxt', '-p', '{}'], args)


if __name__ == '__main__':
    unittest.main()
