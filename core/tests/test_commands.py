from unittest.mock import patch

from app.testing import call_command
from psycopg2 import OperationalError

from app.testing import TestCase


class CommandTests(TestCase):

    def test_wait_for_db_ready(self):
        with patch('app.db.connections.__getitem__') as gi:
            gi.return_value = True
            call_command('wait_for_db')
            self.assertEqual(gi.call_count, 1)

    @patch('time.sleep', return_value=True)
    def test_wait_for_db(self, ts):
        with patch('app.db.connections.__getitem__') as gi:
            gi.side_effect = [OperationalError] * 5 + [True]
            call_command('wait_for_db')
            self.assertEqual(gi.call_count, 6)
