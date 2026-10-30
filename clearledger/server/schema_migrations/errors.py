"""Safe, fixed public errors. Driver messages/SQL/credentials never escape CLI."""

class MigrationError(Exception):
    def __init__(self, code, phase):
        self.code, self.phase = code, phase
        super().__init__(phase)
