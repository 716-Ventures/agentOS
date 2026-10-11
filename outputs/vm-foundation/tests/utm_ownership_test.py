import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('utm_ownership', Path(__file__).resolve().parents[1] / 'utm_ownership.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeVM:
    def __init__(self, identity=None):
        self.identity = identity
        self.calls = []
        self.closed = []
        self.fail_launch = False
        self.refuse_close = False

    def controller(self):
        return '/fixture/utmctl'

    def utm_application_identity(self):
        return self.identity

    def call(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == self.controller() and self.identity is None:
            self.identity = (42, 'launch start')
            if self.fail_launch:
                raise RuntimeError('controller failed after launch')
        return 'stopped'

    def close_owned_utm_application(self, identity):
        self.closed.append(identity)
        if self.refuse_close:
            return False
        assert identity == self.identity
        self.identity = None
        return True


class Ownership(unittest.TestCase):
    def test_controlled_launch_and_exact_cleanup_restore_call(self):
        vm = FakeVM(); original = vm.call
        with module.UTMApplicationOwnership(vm) as scope:
            vm.call([vm.controller(), 'status'])
            self.assertEqual(scope.owned, (42, 'launch start'))
            self.assertTrue(scope.close())
        self.assertEqual(vm.call, original)
        self.assertEqual(vm.closed, [(42, 'launch start')])

    def test_failed_controller_launch_is_still_owned(self):
        vm = FakeVM(); vm.fail_launch = True
        with module.UTMApplicationOwnership(vm) as scope:
            with self.assertRaisesRegex(RuntimeError, 'after launch'):
                vm.call([vm.controller(), 'start'])
            self.assertEqual(scope.owned, vm.identity)
            self.assertTrue(scope.close())

    def test_preexisting_application_is_preserved(self):
        vm = FakeVM((10, 'user start'))
        with module.UTMApplicationOwnership(vm) as scope:
            vm.call([vm.controller(), 'status'])
            self.assertIsNone(scope.owned)
            self.assertFalse(scope.close())
        self.assertEqual(vm.identity, (10, 'user start'))
        self.assertEqual(vm.closed, [])

    def test_replacement_is_neither_operated_nor_closed(self):
        vm = FakeVM()
        with module.UTMApplicationOwnership(vm) as scope:
            vm.call([vm.controller(), 'start'])
            for replacement in [(99, 'other start'), (42, 'recycled PID start')]:
                vm.identity = replacement
                with self.assertRaisesRegex(RuntimeError, 'unowned'):
                    vm.call([vm.controller(), 'stop'])
                with self.assertRaisesRegex(RuntimeError, 'unowned'):
                    scope.close()
        self.assertEqual(len(vm.calls), 1)
        self.assertEqual(vm.closed, [])

    def test_application_not_launched_by_controller_cannot_be_claimed(self):
        vm = FakeVM()
        with module.UTMApplicationOwnership(vm) as scope:
            vm.call(['unrelated-tool'])
            vm.identity = (99, 'external start')
            with self.assertRaisesRegex(RuntimeError, 'claim'):
                scope.close()
        self.assertIsNone(scope.owned)
        self.assertEqual(vm.closed, [])

    def test_failed_exit_is_not_reported_as_success(self):
        vm = FakeVM(); vm.refuse_close = True
        with module.UTMApplicationOwnership(vm) as scope:
            vm.call([vm.controller(), 'start'])
            with self.assertRaisesRegex(RuntimeError, 'not verified'):
                scope.close()

    def test_scope_restores_call_when_body_fails(self):
        vm = FakeVM(); original = vm.call
        with self.assertRaises(ValueError):
            with module.UTMApplicationOwnership(vm):
                raise ValueError('fixture')
        self.assertEqual(vm.call, original)
