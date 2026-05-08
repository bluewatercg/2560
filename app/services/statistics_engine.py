from sqlalchemy import text
class StatisticsEngine:
    def __init__(self, db):
        self.db = db
    def rebuild(self, batch_id: int):
        self.db.execute(text('DELETE FROM structure_2560_statistics WHERE batch_id=:b'), {'b': batch_id})
        self.db.execute(text("""
            INSERT INTO structure_2560_statistics (batch_id,stat_date,stat_type,group_key,sample_count)
            SELECT batch_id,COALESCE(MAX(signal_time DIV 1000000),0),'BY_STRUCTURE_STATUS',structure_status,COUNT(*)
            FROM structure_2560_analysis WHERE batch_id=:b GROUP BY batch_id,structure_status
        """), {'b': batch_id})
        self.db.commit()
        return {'batch_id': batch_id, 'status': 'statistics rebuilt'}
