import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

class GameTests(unittest.TestCase):
    def setup_game(self):
        room = server.make_room('ABCDEF')
        for i, island in enumerate(('Verdantia', 'Pyrrhos')):
            p = server.new_player(f'P{i}', f'tok{i}', i)
            p['island'] = island
            room['players'].append(p)
        room['host'] = 0
        server.start(room)
        return room

    def test_start_requires_two_players_and_islands(self):
        room = server.make_room('ABCDEF')
        p = server.new_player('P0', 'tok0', 0)
        room['players'].append(p)
        with self.assertRaises(ValueError):
            server.start(room)
        room['players'].append(server.new_player('P1', 'tok1', 1))
        with self.assertRaises(ValueError):
            server.start(room)

    def test_build_scores_and_produces_at_round_end(self):
        room = self.setup_game()
        farm, other = room['players']
        server.act(room, farm, {'action': 'build', 'plot': 0, 'building': 'farm'})
        self.assertEqual(farm['energy'], 1)
        self.assertEqual(farm['prosperity'], 1)
        server.act(room, other, {'action': 'pass'})
        server.advance_if_ready(room)
        self.assertEqual(room['round'], 2)
        self.assertEqual(farm['food'], 3)
        self.assertEqual(room['core'], 52)

    def test_players_act_in_seat_order(self):
        room = self.setup_game()
        first, second = room['players']
        self.assertEqual(room['turn_seat'], first['seat'])
        with self.assertRaisesRegex(ValueError, 'Wait for your turn'):
            server.act(room, second, {'action': 'pass'})
        server.act(room, first, {'action': 'pass'})
        self.assertEqual(room['turn_seat'], second['seat'])
        self.assertTrue(first['ready'])
        self.assertFalse(second['ready'])
        server.act(room, second, {'action': 'pass'})
        self.assertEqual(room['round'], 2)
        self.assertEqual(room['turn_seat'], first['seat'])

    def test_setting_a_law_uses_the_action_and_applies_next_round(self):
        room = self.setup_game()
        first, second = room['players']
        server.act(room, first, {'action': 'set_law', 'law': 'harvest'})
        self.assertTrue(first['ready'])
        self.assertEqual(room['turn_seat'], second['seat'])
        self.assertEqual(room['law'], 'balanced')
        self.assertEqual(room['next_law'], 'harvest')
        server.act(room, second, {'action': 'pass'})
        self.assertEqual(room['round'], 2)
        self.assertEqual(room['law'], 'harvest')
        self.assertIsNone(room['next_law'])

    def test_one_action_per_round(self):
        room = self.setup_game()
        p = room['players'][0]
        server.act(room, p, {'action': 'gather', 'resource': 'food'})
        with self.assertRaises(ValueError):
            server.act(room, p, {'action': 'gather', 'resource': 'energy'})

    def test_gather_only_allows_food_or_energy(self):
        room = self.setup_game()
        p = room['players'][0]
        server.act(room, p, {'action': 'gather', 'resource': 'food'})
        self.assertEqual(p['food'], 4)
        with self.assertRaises(ValueError):
            server.act(room, room['players'][1], {'action': 'gather', 'resource': 'influence'})

    def test_unaffordable_build_does_not_consume_action(self):
        room = self.setup_game()
        p = room['players'][0]
        p['food'] = 0
        p['energy'] = 0
        with self.assertRaises(ValueError):
            server.act(room, p, {'action': 'build', 'plot': 0, 'building': 'monument'})
        self.assertFalse(p['ready'])
        self.assertIsNone(p['plots'][0])

    def test_repair_cost_and_cap(self):
        room = self.setup_game()
        p = room['players'][0]
        room['core'] = 52
        server.act(room, p, {'action': 'repair'})
        self.assertEqual(room['core'], 60)
        self.assertEqual(p['energy'], 1)
        with self.assertRaises(ValueError):
            server.act(room, room['players'][1], {'action': 'repair'})

    def test_core_collapse_ends_everyone(self):
        room = self.setup_game()
        room['core'] = 8
        for p in room['players']:
            server.act(room, p, {'action': 'pass'})
        server.advance_if_ready(room)
        self.assertEqual(room['phase'], 'collapsed')
        self.assertIsNone(room['winner'])

    def test_eight_rounds_award_high_score(self):
        room = self.setup_game()
        room['round'] = 8
        room['core'] = 60
        room['players'][0]['prosperity'] = 2
        room['players'][1]['prosperity'] = 1
        for p in room['players']:
            server.act(room, p, {'action': 'pass'})
        server.advance_if_ready(room)
        self.assertEqual(room['phase'], 'finished')
        self.assertEqual(room['winner'], 0)

    def test_setting_law_uses_action_and_changes_next_round_income_and_core_cost(self):
        room = self.setup_game()
        farm, other = room['players']
        farm['plots'][0] = {'type': 'farm', 'level': 1}
        farm['food'] = 0
        farm['prosperity'] = 1
        server.act(room, farm, {'action': 'set_law', 'law': 'harvest'})
        server.act(room, other, {'action': 'pass'})
        self.assertEqual(room['round'], 2)
        self.assertEqual(room['law'], 'harvest')
        self.assertEqual(farm['food'], 1)  # round one used Balanced
        self.assertEqual(room['core'], 52)
        server.act(room, farm, {'action': 'pass'})
        server.act(room, other, {'action': 'pass'})
        self.assertEqual(room['round'], 3)
        self.assertEqual(farm['food'], 3)  # Harvest adds one per Farm
        self.assertEqual(room['core'], 42)

    def test_later_player_can_change_the_next_round_law(self):
        room = self.setup_game()
        first, second = room['players']
        server.act(room, first, {'action': 'set_law', 'law': 'harvest'})
        server.act(room, second, {'action': 'set_law', 'law': 'power'})
        self.assertEqual(room['round'], 2)
        self.assertEqual(room['law'], 'power')
        self.assertEqual(room['law_set_by'], None)

    def test_trade_requires_consent_and_transfers_both_resources(self):
        room = self.setup_game()
        giver, receiver = room['players']
        server.act(room, giver, {'action': 'trade_offer', 'target': receiver['seat'], 'give': 'food', 'want': 'energy'})
        self.assertEqual(giver['food'], 1)  # held while the offer is open
        self.assertTrue(giver['ready'])
        self.assertEqual(receiver['food'], 2)  # nothing transfers without consent
        server.act(room, receiver, {'action': 'trade_accept'})
        self.assertIsNone(room['trade'])
        self.assertEqual(giver['energy'], 3)
        self.assertEqual(receiver['food'], 3)
        self.assertEqual(receiver['energy'], 1)
        self.assertFalse(receiver['ready'])

    def test_declined_trade_returns_escrow(self):
        room = self.setup_game()
        giver, receiver = room['players']
        server.act(room, giver, {'action': 'trade_offer', 'target': receiver['seat'], 'give': 'energy', 'want': 'food'})
        server.act(room, receiver, {'action': 'pass'})
        self.assertEqual(giver['energy'], 2)
        self.assertIsNone(room['trade'])

    def test_island_choices_are_unique(self):
        room = self.setup_game()
        room['phase'] = 'lobby'
        with self.assertRaises(ValueError):
            server.act(room, room['players'][1], {'action': 'choose', 'island': 'Verdantia'})

    def test_public_state_hides_tokens(self):
        room = self.setup_game()
        state = server.public(room, 'tok0')
        self.assertTrue(state['players'][0]['you'])
        self.assertNotIn('token', state['players'][0])

if __name__ == '__main__':
    unittest.main()
