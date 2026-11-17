"""Options > Environment Variables edits nxt's env files.

nxt sets environment variables from env files as it starts. The dialog is
those files as a table: nothing is written until Apply, a project file is
an env file anywhere that the user's own file includes, and what is applied
reaches the running session without ever replacing a variable that was set
outside nxt.
"""
# Builtin
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# External
from Qt import QtWidgets

# Internal
from nxt_editor import env_dialog

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

if env_dialog.available():
    from nxt import env_files


@unittest.skipUnless(env_dialog.available(),
                     'needs an nxt core with env files')
class EnvDialogCase(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='nxt_env_dialog_')
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.user = os.path.join(self.folder, 'user', 'env.json')
        self.site = os.path.join(self.folder, 'site', 'env.json')
        self.project = os.path.join(self.folder, 'project', 'nxt_env.json')
        os.makedirs(os.path.dirname(self.project))
        # Nobody's real env files, and nobody's real environment.
        for patch in (mock.patch.object(env_files, 'USER_ENV_FILE', self.user),
                      mock.patch.object(env_files, 'SITE_ENV_FILE', self.site),
                      mock.patch.object(env_files, '_applied', {}),
                      mock.patch.dict(os.environ, clear=False)):
            patch.start()
            self.addCleanup(patch.stop)
        for name in ('NXT_T_GRAPHS', 'NXT_T_ROOTS',
                     env_files.ENV_FILES_ENV_VAR):
            os.environ.pop(name, None)

    def dialog(self):
        dialog = env_dialog.EnvFilesDialog()
        self.addCleanup(dialog.deleteLater)
        return dialog

    def set_row(self, dialog, name, value):
        dialog.add_variable()
        row = dialog.table.rowCount() - 1
        dialog.table.item(row, env_dialog.NAME_COL).setText(name)
        dialog.table.item(row, env_dialog.VALUE_COL).setText(value)
        return row


class EditingTheUserFile(EnvDialogCase):

    def test_opens_on_the_users_file_before_it_exists(self):
        dialog = self.dialog()
        self.assertEqual(dialog.key(self.user), dialog.current)
        self.assertEqual(0, dialog.table.rowCount())
        self.assertFalse(os.path.isfile(self.user))

    def test_nothing_is_written_until_apply(self):
        dialog = self.dialog()
        self.set_row(dialog, 'NXT_T_GRAPHS', '/graphs')
        self.assertFalse(os.path.isfile(self.user))
        self.assertNotIn('NXT_T_GRAPHS', os.environ)
        self.assertTrue(dialog.apply())
        self.assertEqual('/graphs', os.environ['NXT_T_GRAPHS'])
        self.assertEqual(
            '/graphs',
            env_files.EnvFile.load(self.user).variables['NXT_T_GRAPHS'])

    def test_cancel_leaves_everything_alone(self):
        dialog = self.dialog()
        self.set_row(dialog, 'NXT_T_GRAPHS', '/graphs')
        dialog.reject()
        self.assertFalse(os.path.isfile(self.user))
        self.assertNotIn('NXT_T_GRAPHS', os.environ)

    def test_several_paths_are_saved_as_a_list(self):
        # A list is what nxt joins with each platform's own separator.
        dialog = self.dialog()
        self.set_row(dialog, 'NXT_T_ROOTS', '/a; /b')
        dialog.apply()
        self.assertEqual(
            ['/a', '/b'],
            env_files.EnvFile.load(self.user).variables['NXT_T_ROOTS'])
        self.assertEqual(os.pathsep.join(['/a', '/b']),
                         os.environ['NXT_T_ROOTS'])

    def test_a_list_reads_back_as_it_was_typed(self):
        self.assertEqual('/a; /b', env_dialog.value_to_text(['/a', '/b']))
        self.assertEqual(['/a', '/b'], env_dialog.text_to_value('/a; /b'))
        self.assertEqual('/a', env_dialog.text_to_value(' /a '))

    def test_removing_a_variable_unsets_it(self):
        dialog = self.dialog()
        row = self.set_row(dialog, 'NXT_T_GRAPHS', '/graphs')
        dialog.apply()
        dialog.table.setCurrentCell(row, env_dialog.NAME_COL)
        dialog.remove_variable()
        dialog.apply()
        self.assertNotIn('NXT_T_GRAPHS', os.environ)
        self.assertEqual(
            {}, dict(env_files.EnvFile.load(self.user).variables))

    def test_says_when_a_variable_was_set_outside(self):
        os.environ['NXT_T_GRAPHS'] = '/from/the/launcher'
        dialog = self.dialog()
        row = self.set_row(dialog, 'NXT_T_GRAPHS', '/graphs')
        dialog.apply()
        self.assertEqual('/from/the/launcher', os.environ['NXT_T_GRAPHS'])
        now = dialog.table.item(row, env_dialog.NOW_COL).text()
        self.assertIn('/from/the/launcher', now)
        self.assertIn('set outside nxt', now)


class ProjectFiles(EnvDialogCase):

    def test_a_new_project_file_is_included_by_the_users(self):
        dialog = self.dialog()
        dialog.include_project_file(self.project)
        self.assertEqual(dialog.key(self.project), dialog.current)
        self.set_row(dialog, 'NXT_T_GRAPHS', '$NXT_ENV_FILE_DIR/graphs')
        dialog.apply()
        user = env_files.EnvFile.load(self.user)
        self.assertEqual([self.project.replace(os.sep, '/')], user.include)
        expected = os.path.dirname(self.project).replace(os.sep, '/')
        self.assertEqual(expected + '/graphs', os.environ['NXT_T_GRAPHS'])

    def test_a_project_file_is_listed_the_next_time(self):
        dialog = self.dialog()
        dialog.include_project_file(self.project)
        dialog.apply()
        again = self.dialog()
        self.assertIn(again.key(self.project), again.files)
        self.assertEqual('Project', again.labels[again.key(self.project)])

    def test_removing_a_project_file_keeps_the_file(self):
        dialog = self.dialog()
        dialog.include_project_file(self.project)
        self.set_row(dialog, 'NXT_T_GRAPHS', '/graphs')
        dialog.apply()
        dialog.remove_project_file()
        dialog.apply()
        self.assertTrue(os.path.isfile(self.project))
        self.assertEqual([], env_files.EnvFile.load(self.user).include)
        self.assertNotIn('NXT_T_GRAPHS', os.environ)

    def test_only_a_project_file_can_be_removed(self):
        dialog = self.dialog()
        self.assertFalse(dialog.remove_file_button.isEnabled())
        dialog.include_project_file(self.project)
        self.assertTrue(dialog.remove_file_button.isEnabled())

    def test_a_folder_under_the_file_is_written_from_its_folder(self):
        dialog = self.dialog()
        dialog.include_project_file(self.project)
        row = self.set_row(dialog, 'NXT_T_ROOTS', '')
        inside = os.path.join(os.path.dirname(self.project), 'graphs')
        outside = os.path.join(self.folder, 'elsewhere')
        dialog.add_path_to_row(row, inside)
        dialog.add_path_to_row(row, outside)
        self.assertEqual(
            '$NXT_ENV_FILE_DIR/graphs; ' + outside.replace(os.sep, '/'),
            dialog.table.item(row, env_dialog.VALUE_COL).text())

    def test_files_named_in_the_environment_are_shown(self):
        extra = os.path.join(self.folder, 'extra.json')
        os.environ[env_files.ENV_FILES_ENV_VAR] = extra
        dialog = self.dialog()
        self.assertEqual(env_files.ENV_FILES_ENV_VAR,
                         dialog.labels[dialog.key(extra)])


if __name__ == '__main__':
    unittest.main()
