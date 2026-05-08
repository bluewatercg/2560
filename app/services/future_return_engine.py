class FutureReturnEngine:
    def __init__(self, db):
        self.db = db
    def backfill(self, batch_id=None):
        return {'updated': 0, 'note': 'future return backfill placeholder; enable after confirming trading calendar'}
