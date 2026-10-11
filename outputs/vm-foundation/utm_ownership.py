"""Track only UTM applications launched by this process's controller calls."""


class UTMApplicationOwnership:
    def __init__(self, vm):
        self.vm = vm
        self.initial = vm.utm_application_identity()
        self.expected = self.initial
        self.owned = None
        self.controller = str(vm.controller())
        self.original_call = None

    def __enter__(self):
        self.original_call = self.vm.call
        self.vm.call = self.call
        return self

    def call(self, args, **kwargs):
        if not args or str(args[0]) != self.controller:
            return self.original_call(args, **kwargs)
        before = self.vm.utm_application_identity()
        if before != self.expected:
            raise RuntimeError('UTM application identity changed; refusing to operate an unowned application')
        try:
            return self.original_call(args, **kwargs)
        finally:
            # A controller can launch UTM and then fail. Capture that identity
            # here, at the launch boundary, so failure cleanup still owns it.
            if before is None:
                after = self.vm.utm_application_identity()
                if after is not None:
                    self.expected = self.owned = after

    def close(self):
        current = self.vm.utm_application_identity()
        if self.owned is None:
            if current not in (None, self.initial):
                raise RuntimeError('UTM application identity changed; refusing to claim it during cleanup')
            return False  # A preexisting application is never ours to close.
        if current is None:
            self.expected = None
            return True
        if current != self.owned:
            raise RuntimeError('UTM application identity changed; refusing to close an unowned application')
        if not self.vm.close_owned_utm_application(self.owned):
            raise RuntimeError('Owned UTM application exit was not verified')
        self.expected = None
        return True

    def __exit__(self, *_):
        self.vm.call = self.original_call
