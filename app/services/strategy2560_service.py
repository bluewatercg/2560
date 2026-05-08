from sqlalchemy import text

def rows(result):
    return [dict(r._mapping) for r in result]

class Strategy2560Service:
    def __init__(self, db):
        self.db = db
    def overview(self):
        lb = self.db.execute(text("SELECT batch_id,run_time,strategy_code,strategy_version,status FROM analysis_batch WHERE strategy_code='S2560' ORDER BY run_time DESC LIMIT 1")).mappings().first()
        p = {'b': lb['batch_id']} if lb else {}
        wf = 'WHERE batch_id=:b' if lb else ''
        s = self.db.execute(text(f"SELECT COUNT(*) total_signals,SUM(structure_status='结构完整') complete_count,SUM(structure_status='部分满足') partial_count,SUM(structure_status='明显缺失') missing_count,SUM(structure_status='数据不足') data_insufficient_count FROM structure_2560_analysis {wf}"), p).mappings().first()
        t = rows(self.db.execute(text(f"SELECT tag_name,COUNT(*) count FROM structure_2560_tag_detail {wf} GROUP BY tag_name ORDER BY count DESC LIMIT 20"), p))
        return {'latest_batch': dict(lb) if lb else None, 'summary': dict(s) if s else {}, 'tag_distribution': t}
    def list_signals(self, page=1, page_size=50, code=None, structure_status=None, tag=None, batch_id=None, selected_signal=None):
        where=[]; p={'limit': page_size, 'offset': (page-1)*page_size}
        if code: where.append('a.code=:code'); p['code']=code
        if structure_status: where.append('a.structure_status=:st'); p['st']=structure_status
        if batch_id: where.append('a.batch_id=:batch_id'); p['batch_id']=batch_id
        if selected_signal is not None: where.append('a.selected_signal=:selected_signal'); p['selected_signal']=selected_signal
        if tag: where.append('EXISTS (SELECT 1 FROM structure_2560_tag_detail t WHERE t.analysis_id=a.id AND t.tag_name=:tag)'); p['tag']=tag
        ws='WHERE ' + ' AND '.join(where) if where else ''
        total=self.db.execute(text(f'SELECT COUNT(*) FROM structure_2560_analysis a {ws}'), p).scalar_one()
        items=rows(self.db.execute(text(f"SELECT a.id,a.batch_id,a.code,a.name,a.signal_time,a.signal_period,a.price,a.structure_status,a.missing_tags,a.missing_tag_count,a.explain_text,a.data_quality_status,a.selected_signal,s.industry_name,s.board_name FROM structure_2560_analysis a LEFT JOIN stock_info s ON s.code=a.code {ws} ORDER BY a.signal_time DESC,a.id DESC LIMIT :limit OFFSET :offset"), p))
        return {'total': total, 'page': page, 'page_size': page_size, 'items': items}
    def signal_detail(self, signal_id):
        r=self.db.execute(text('SELECT * FROM structure_2560_analysis WHERE id=:id'), {'id': signal_id}).mappings().first()
        if not r: return None
        tags=rows(self.db.execute(text('SELECT tag_code,tag_name,tag_type FROM structure_2560_tag_detail WHERE analysis_id=:id'), {'id': signal_id}))
        return {'base_info': dict(r), 'tags': tags}
    def complete_cases(self, limit=20):
        return rows(self.db.execute(text("SELECT * FROM structure_2560_analysis WHERE structure_status='结构完整' AND selected_signal=1 ORDER BY signal_time DESC LIMIT :l"), {'l': limit}))
    def statistics(self, stat_type=None, batch_id=None):
        where=[]; p={}
        if stat_type: where.append('stat_type=:t'); p['t']=stat_type
        if batch_id: where.append('batch_id=:b'); p['b']=batch_id
        ws='WHERE ' + ' AND '.join(where) if where else ''
        return rows(self.db.execute(text(f'SELECT * FROM structure_2560_statistics {ws} ORDER BY stat_date DESC,id DESC LIMIT 500'), p))
    def batches(self, limit=50):
        return rows(self.db.execute(text('SELECT batch_id,batch_name,run_time,data_source,strategy_code,strategy_version,status,message FROM analysis_batch ORDER BY run_time DESC LIMIT :l'), {'l': limit}))
    def batch_detail(self, batch_id):
        r=self.db.execute(text('SELECT * FROM analysis_batch WHERE batch_id=:b'), {'b': batch_id}).mappings().first()
        return dict(r) if r else None
    def data_quality_summary(self):
        return rows(self.db.execute(text('SELECT * FROM data_quality_check ORDER BY check_date DESC,period LIMIT 100')))
