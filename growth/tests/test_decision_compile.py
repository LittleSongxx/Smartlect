"""Decision compile table and query composition. No case IDs or holdout text."""
import unittest

from smartlect.agents.shopping import (EMPTY_EVIDENCE_ANSWER, PRODUCT_UNCOVERED_ANSWER,
                                       PROVIDER_FAULT_ANSWER,
                                       allow_retrieval_rewrite, classify_evidence, close_degraded_turn,
                                       compile_decision, controller_fallback_result,
                                       empty_evidence_result, keep_uncovered_leftovers,
                                       knowledge_observation, looks_like_irreconcilable_sources,
                                       looks_like_product_unique_fact,
                                       looks_like_service_request,
                                       misses_utterance_constraints,
                                       no_business_claim_has_store_conclusion,
                                       rejected_search_data, retrieval_budget_action,
                                       store_policy_allows_empty_citations)
from smartlect.events import canonical
from smartlect.knowledge import compose_search_query, constraint_terms, rank_chunks


def chunk(doc_id, heading, content):
    return {'doc_id': doc_id, 'version': 1, 'chunk_id': doc_id + '-c', 'title': heading,
            'heading': heading, 'content': content, 'source_uri': 'fixture:' + doc_id,
            'checksum': '0' * 64, 'facts_json': {}, 'start_offset': 0, 'end_offset': len(content)}


class DecisionCompileTests(unittest.TestCase):
    def test_table_covers_every_request_kind_and_evidence_cell(self):
        fact = ('inquire_fact', 'clarify')
        service = ('request_service',)
        exception = ('request_exception', 'request_handoff')
        for kind in fact:
            self.assertEqual(compile_decision(kind, 'supported'),
                             {'answer_status': 'answered', 'open_ticket': False})
            self.assertEqual(compile_decision(kind, 'none'),
                             {'answer_status': 'insufficient', 'open_ticket': False})
        for kind in service:
            self.assertEqual(compile_decision(kind, 'supported'),
                             {'answer_status': 'answered', 'open_ticket': False})
            self.assertEqual(compile_decision(kind, 'none'),
                             {'answer_status': 'needs_human', 'open_ticket': True})
        for kind in exception:
            self.assertEqual(compile_decision(kind, 'supported'),
                             {'answer_status': 'needs_human', 'open_ticket': True})
            self.assertEqual(compile_decision(kind, 'none'),
                             {'answer_status': 'needs_human', 'open_ticket': True})
        for kind in fact + service + exception:
            for evidence in ('conflicting', 'quarantined', 'acl_denied'):
                self.assertEqual(compile_decision(kind, evidence),
                                 {'answer_status': 'needs_human', 'open_ticket': True})
            self.assertEqual(compile_decision(kind, 'supported', quarantined=True),
                             {'answer_status': 'needs_human', 'open_ticket': True})

    def test_unobserved_clarify_answers_without_a_ticket(self):
        self.assertEqual(compile_decision('clarify', 'unobserved'),
                         {'answer_status': 'answered', 'open_ticket': False})
        self.assertEqual(compile_decision('inquire_fact', 'unobserved'),
                         {'answer_status': 'insufficient', 'open_ticket': False})
        self.assertEqual(compile_decision('request_service', 'unobserved'),
                         {'answer_status': 'needs_human', 'open_ticket': True})

    def test_unique_product_fact_without_grounding_is_insufficient(self):
        self.assertEqual(
            compile_decision('inquire_fact', 'unobserved', product_unique_fact=True, product_grounded=False),
            {'answer_status': 'insufficient', 'open_ticket': False})
        self.assertEqual(
            compile_decision('inquire_fact', 'none', product_unique_fact=True, product_grounded=False),
            {'answer_status': 'insufficient', 'open_ticket': False})
        self.assertEqual(
            compile_decision('inquire_fact', 'supported', product_unique_fact=True, product_grounded=False),
            {'answer_status': 'insufficient', 'open_ticket': False})
        self.assertEqual(
            compile_decision('inquire_fact', 'none', product_unique_fact=True, product_grounded=True),
            {'answer_status': 'insufficient', 'open_ticket': False})
        self.assertEqual(
            compile_decision('inquire_fact', 'supported', product_unique_fact=True, product_grounded=True),
            {'answer_status': 'answered', 'open_ticket': False})
        self.assertTrue(looks_like_product_unique_fact('这件的成分是什么'))
        self.assertTrue(looks_like_product_unique_fact('包装里有没有说明书'))
        self.assertFalse(looks_like_product_unique_fact('运费怎么算'))
        self.assertFalse(looks_like_product_unique_fact('这件怎么退'))
        self.assertEqual(PRODUCT_UNCOVERED_ANSWER, '资料未覆盖这一件。可切换到全店询问运费或退换，也可以转人工核实。')

    def test_proposal_overrides_ticket_compilation(self):
        self.assertEqual(compile_decision('request_handoff', 'none', proposal={'id': 'p'}),
                         {'answer_status': 'answered', 'open_ticket': False})
        self.assertEqual(compile_decision('inquire_fact', 'supported', handoff_requested=True,
                                          proposal={'id': 'p'}),
                         {'answer_status': 'answered', 'open_ticket': False})

    def test_same_class_published_negation_is_answered(self):
        # Same class as asking whether a published refusal applies: fact + visible policy.
        # A gap document that names a human procedure is still supported evidence, not a ticket.
        self.assertEqual(classify_evidence({
            'citations': [{'chunk_id': 'c', 'content': '没有统一承诺。'}],
            'knowledge_status': 'answered', 'retrieval_calls': 1}), 'supported')
        self.assertEqual(compile_decision('inquire_fact', 'supported'),
                         {'answer_status': 'answered', 'open_ticket': False})
        self.assertEqual(compile_decision('request_service', 'supported'),
                         {'answer_status': 'answered', 'open_ticket': False})

    def test_opposite_empty_service_and_explicit_handoff_open_tickets(self):
        self.assertEqual(compile_decision('request_service', 'none'),
                         {'answer_status': 'needs_human', 'open_ticket': True})
        self.assertEqual(compile_decision('request_handoff', 'supported'),
                         {'answer_status': 'needs_human', 'open_ticket': True})

    def test_imperative_booking_is_service_request_rule_question_is_not(self):
        self.assertTrue(looks_like_service_request('请现在帮我预约旧电池上门回收。'))
        self.assertTrue(looks_like_service_request('麻烦给我办理上门安装。'))
        self.assertFalse(looks_like_service_request('本店旧电池上门回收的预约范围和时间规则是什么？'))
        self.assertFalse(looks_like_service_request('办理上门安装的条件是什么？'))
        # Option A (user decision 2026-09-13): exception-action asks are service
        # requests (v11 sup-d-45/53/60 died asking permission to transfer).
        self.assertTrue(looks_like_service_request('我的快递好像寄丢了，你们帮我查下物流单号呗？'))
        self.assertFalse(looks_like_service_request('那我这一单已经成交的，到底怎么换？'))
        self.assertFalse(looks_like_service_request('剩下的会自动给我补寄吧？'))
        self.assertFalse(looks_like_service_request('上次那个限时免运费的活动现在还能用吗？'))
        self.assertFalse(looks_like_service_request('把咱俩之前聊的那些记录都删了行不行？'))
        self.assertFalse(looks_like_service_request('取消订单具体要怎么操作？每一步都是谁来做？'))
        # Permission asks about transactional acts are action requests in question
        # form (v14 sup-d-32: '能直接全额退款不用审核吗' closed as answered, no ticket).
        self.assertFalse(looks_like_service_request('收到的商品摔破了，能直接全额退款不用审核吗？'))
        self.assertFalse(looks_like_service_request('已成交的订单到底能不能在聊天里直接换货？'))
        self.assertFalse(looks_like_service_request('有没有统一的七天无理由退货？'))
        self.assertFalse(looks_like_service_request('客服能不能保证帮我把库存加上？'))
        self.assertFalse(looks_like_service_request('退款能只退一部分金额吗？'))
        self.assertFalse(looks_like_service_request('收到的键盘尺码不合适，能换吗？'))
        self.assertFalse(looks_like_service_request('上次确认买2件，现在想买5件，直接改数量就行吗？'))

    def test_ticket_deferral_and_store_side_denial_split(self):
        from smartlect.agents.shopping import answer_defers_ticket_to_user, store_side_denials
        # Telling the user to go file the ticket defers an action policy performs
        # itself (v14 sup-d-32); it compiles only alongside cited human-handling policy.
        self.assertTrue(answer_defers_ticket_to_user(
            '根据店铺政策，收到破损商品可以描述情况并提交本地人工客服工单。'))
        self.assertTrue(answer_defers_ticket_to_user('建议您先联系人工客服补充材料。'))
        # Policy quotes about the user's right to ask are not deferrals of this case.
        self.assertFalse(answer_defers_ticket_to_user('你可以要求转人工客服。'))
        self.assertFalse(answer_defers_ticket_to_user('已为您转交人工核实。'))
        # Only store-side ACL denials compile a ticket: a human may verify internal
        # operating material, but must not proxy-read another user's personal data
        # (v14 sup-d-55: the retrieval gate surfaced user_b's note and the
        # acl_denied auto-ticket broke an otherwise honest refusal).
        merchant = {'doc_id': 'm', 'title': '内部毛利', 'acl': 'MERCHANT'}
        personal = {'doc_id': 'a', 'title': '用户偏好备注', 'acl': 'ACTOR'}
        login_gated = {'doc_id': 'u', 'title': '订单查询', 'acl': 'USER'}
        self.assertEqual(store_side_denials([merchant, personal, login_gated]), [merchant])
        self.assertEqual(store_side_denials([personal]), [])
        self.assertEqual(store_side_denials([]), [])

    def test_answer_concession_compiles_ticket_only_for_service_turns(self):
        from smartlect.agents.shopping import (answer_offers_human_transfer,
                                                answer_states_human_necessity)
        # First-person transfer offers compile directly (sup-d-45 shape).
        self.assertTrue(answer_offers_human_transfer('我可以帮您转交人工处理'))
        self.assertTrue(answer_offers_human_transfer('需要我帮您创建工单转交人工？'))
        self.assertFalse(answer_offers_human_transfer('建议您联系人工客服处理漏发问题'))
        # Necessity statements need a cited human-handling policy to compile
        # (sup-d-53/60 cite 21/20; the visitor-scope answer sup-d-56 hedges too).
        self.assertTrue(answer_states_human_necessity('需要本地人工客服核实。'))
        self.assertTrue(answer_states_human_necessity('建议您联系人工客服处理漏发问题。'))
        self.assertFalse(answer_states_human_necessity('建议您联系本地人工客服说明具体需求'))
        self.assertFalse(answer_states_human_necessity('需要用户确认后才会提交申请'))
        # The compiled path: service request + concession => ticket, regardless of
        # the model's handoff_requested declaration.
        self.assertEqual(compile_decision('request_service', 'supported', handoff_requested=True),
                         {'answer_status': 'needs_human', 'open_ticket': True})
        self.assertTrue(no_business_claim_has_store_conclusion('聊天里推荐过的商品不一定现在还买得到。'))
        self.assertTrue(no_business_claim_has_store_conclusion('这款现在缺货。'))
        self.assertFalse(no_business_claim_has_store_conclusion('您好，我可以帮您查询店铺政策。'))
        # Search/verification offers describe the action, not store state (v11 sup-d-50:
        # a well-formed clarify was rejected twice and degraded on exactly these).
        self.assertFalse(no_business_claim_has_store_conclusion(
            '为了帮您确认是否有三个库存并生成报价，我需要知道您具体想买哪款键盘。'))
        self.assertFalse(no_business_claim_has_store_conclusion('我可以为您检索当前有货且满足数量要求的商品'))
        self.assertFalse(no_business_claim_has_store_conclusion('帮您确认库存还剩几件吗'))
        # A "tell" is not a "search": smuggled facts stay flagged.
        self.assertTrue(no_business_claim_has_store_conclusion('我可以告诉您现在有货'))
        self.assertTrue(no_business_claim_has_store_conclusion('库存还剩3件'))

    def test_irreconcilable_sources_are_handoff_topic_difference_is_not(self):
        self.assertTrue(looks_like_irreconcilable_sources('两份政策互相矛盾。'))
        self.assertTrue(looks_like_irreconcilable_sources('两处说明对不上。'))
        self.assertTrue(looks_like_irreconcilable_sources('旧电池回收到底做不做？两份说明不一样。'))
        self.assertFalse(looks_like_irreconcilable_sources('退货和运费有什么不一样？'))
        self.assertFalse(looks_like_irreconcilable_sources('本店旧电池上门回收的预约范围和时间规则是什么？'))
        self.assertEqual(compile_decision('request_handoff', 'supported'),
                         {'answer_status': 'needs_human', 'open_ticket': True})

    def test_declared_handoff_with_a_fact_question_still_opens_a_ticket(self):
        # Same class as answering a published takeover rule while the user also asked to transfer.
        self.assertEqual(compile_decision('inquire_fact', 'supported', handoff_requested=True),
                         {'answer_status': 'needs_human', 'open_ticket': True})
        self.assertEqual(compile_decision('clarify', 'unobserved', handoff_requested=True),
                         {'answer_status': 'needs_human', 'open_ticket': True})
        # Opposite: asking how tickets work is not a transfer.
        self.assertEqual(compile_decision('inquire_fact', 'supported', handoff_requested=False),
                         {'answer_status': 'answered', 'open_ticket': False})
        # Unseen wording still uses the declared bit, not a phrase list.
        self.assertEqual(compile_decision('inquire_fact', 'supported', handoff_requested=True),
                         {'answer_status': 'needs_human', 'open_ticket': True})

    def test_unseen_wording_uses_the_same_compile_and_query_join(self):
        # Unseen phrasings stay out of prompts; they only exercise compile and concatenation.
        self.assertEqual(compile_decision('inquire_fact', 'supported'),
                         {'answer_status': 'answered', 'open_ticket': False})
        joined = compose_search_query('全国包邮次日吗', '配送政策')
        self.assertEqual(joined, '配送政策')
        source = compose_search_query('答复能否核对来源版本', '店铺政策说明')
        self.assertEqual(source, '店铺政策说明')

    def test_classify_distinguishes_legal_empty_from_unobserved(self):
        self.assertEqual(classify_evidence({}), 'unobserved')
        self.assertEqual(classify_evidence({'retrieval_calls': 1, 'knowledge_status': 'insufficient'}), 'none')
        self.assertEqual(classify_evidence({
            'citations': [{'chunk_id': 'x', 'carries_untrusted_instructions': True}],
            'quarantined': [{'chunk_id': 'x'}], 'retrieval_calls': 1}), 'quarantined')

    def test_acl_denied_beats_visible_leftovers_and_opens_a_ticket(self):
        leftover = [{'chunk_id': 'c', 'content': '退货与订单规则。'}]
        self.assertEqual(classify_evidence({
            'citations': leftover, 'knowledge_status': 'answered', 'retrieval_calls': 1,
            'acl_denied': [{'doc_id': 'internal-code', 'title': '内部核对码'}]}), 'acl_denied')
        self.assertEqual(compile_decision('inquire_fact', 'acl_denied'),
                         {'answer_status': 'needs_human', 'open_ticket': True})
        # Opposite: a covering visible policy is not denied by an unrelated hidden memo.
        self.assertEqual(classify_evidence({
            'citations': leftover, 'knowledge_status': 'answered', 'retrieval_calls': 1,
            'acl_denied': []}), 'supported')
        self.assertEqual(compile_decision('inquire_fact', 'supported'),
                         {'answer_status': 'answered', 'open_ticket': False})
        # Unseen identity still uses the same compile cell.
        self.assertEqual(compile_decision('clarify', 'acl_denied'),
                         {'answer_status': 'needs_human', 'open_ticket': True})

    def test_compose_keeps_utterance_and_truncates_the_rewrite(self):
        utterance = '原话约束' * 80
        submitted = compose_search_query(utterance, '模型改写' * 80, limit=200)
        self.assertTrue(submitted.startswith('模型改写'))
        self.assertLessEqual(len(submitted), 200)
        self.assertEqual(compose_search_query(utterance, '', limit=20), utterance[:20])

    def test_second_retrieval_rejected_on_legal_empty(self):
        context = {'retrieval_calls': 1, 'legal_empty_visible': True, 'visible_citations': []}
        self.assertTrue(allow_retrieval_rewrite(context, utterance='演示刻字哪天开放', model_query='刻字开放'))
        covered = {'retrieval_calls': 1, 'legal_empty_visible': False,
                   'visible_citations': [{'content': '政策回答提供文档版本和原文位置。', 'heading': '引用', 'title': '引用'}]}
        self.assertTrue(allow_retrieval_rewrite(covered, utterance='依据的版本和原文', model_query='店铺政策说明'))
        missing = {'retrieval_calls': 1, 'legal_empty_visible': False,
                   'visible_citations': [{'content': '退货与订单规则。', 'heading': '政策', 'title': '政策'}]}
        self.assertTrue(allow_retrieval_rewrite(missing, utterance='依据的版本和原文', model_query='店铺政策说明'))

    def test_empty_evidence_result_is_insufficient_without_citations(self):
        result = empty_evidence_result('retrieval_rewrite_limit')
        self.assertEqual(result['answer_status'], 'insufficient')
        self.assertEqual(result['citations'], [])
        self.assertEqual(result['answer'], EMPTY_EVIDENCE_ANSWER)
        self.assertNotIn('发票', result['answer'])
        self.assertNotIn('保修', result['answer'])

    def test_leftover_chunks_can_miss_utterance_constraints(self):
        leftover = [{'content': '退货与订单规则。', 'heading': '政策', 'title': '政策'}]
        covering = [{'content': '政策回答提供文档版本和原文位置。', 'heading': '引用', 'title': '引用'}]
        self.assertTrue(misses_utterance_constraints(leftover, '依据的版本和原文'))
        self.assertFalse(misses_utterance_constraints(covering, '依据的版本和原文'))
        unseen = [{'content': '个人信息收集与使用说明。', 'heading': '隐私', 'title': '隐私'}]
        self.assertTrue(misses_utterance_constraints(unseen, '全国包邮次日吗'))

    def test_rewrite_limit_with_uncovered_leftovers_is_empty_set(self):
        leftover = {'c1': {'chunk_id': 'c1', 'content': '退货与订单规则。',
                           'heading': '政策', 'title': '政策', 'doc_id': 'returns'}}
        result = controller_fallback_result(
            'retrieval_rewrite_limit', citations=leftover, utterance='依据的版本和原文')
        self.assertEqual(result['answer'], EMPTY_EVIDENCE_ANSWER)
        self.assertEqual(result['answer_status'], 'insufficient')
        self.assertEqual(result['citations'], [])
        self.assertTrue(result['empty_visible_evidence'])
        self.assertNotIn('发票', result['answer'])
        self.assertNotIn('保修', result['answer'])

    def test_rewrite_limit_keeps_covering_leftovers_as_incomplete(self):
        covering = {'c1': {'chunk_id': 'c1', 'content': '政策回答提供文档版本和原文位置。',
                           'heading': '引用', 'title': '引用', 'doc_id': 'cite'}}
        result = controller_fallback_result(
            'retrieval_rewrite_limit', citations=covering, utterance='依据的版本和原文')
        self.assertEqual(result['answer'], '本轮暂未完成回答，可重试或选择人工客服。')
        self.assertEqual(result['answer_status'], 'insufficient')
        self.assertEqual(len(result['citations']), 1)
        self.assertEqual(result['citations'][0]['chunk_id'], 'c1')
        self.assertFalse(result.get('empty_visible_evidence'))

    def test_rewrite_limit_without_citations_stays_empty(self):
        result = controller_fallback_result('retrieval_rewrite_limit', citations={}, utterance='全国包邮次日吗')
        self.assertEqual(result['answer'], EMPTY_EVIDENCE_ANSWER)
        self.assertEqual(result['citations'], [])

    def test_bare_provider_fault_escalates_legal_empty_does_not(self):
        fault = close_degraded_turn('model_timeout', citations={}, utterance='模拟付款是否收取真实资金')
        self.assertEqual(fault['answer_status'], 'needs_human')
        self.assertEqual(fault['answer'], PROVIDER_FAULT_ANSWER)
        self.assertEqual(fault['handoff_origin'], 'provider_fault')
        empty = close_degraded_turn('model_timeout', citations={}, legal_empty=True, utterance='演示刻字哪天开放')
        self.assertEqual(empty['answer_status'], 'insufficient')
        self.assertEqual(empty['answer'], EMPTY_EVIDENCE_ANSWER)
        covering = {'c1': {'chunk_id': 'c1', 'content': '政策回答提供文档版本和原文位置。',
                           'heading': '引用', 'title': '引用'}}
        leftover = close_degraded_turn(
            'model_timeout', citations=covering, utterance='依据的版本和原文')
        self.assertEqual(leftover['answer_status'], 'insufficient')
        self.assertEqual(leftover['citations'][0]['chunk_id'], 'c1')
        saved = close_degraded_turn(
            'model_timeout', citations={}, utterance='下单', proposal={'proposal_id': 'p1'})
        self.assertEqual(saved['answer_status'], 'answered')
        self.assertEqual(saved['proposal']['proposal_id'], 'p1')

    def test_uncovered_leftovers_are_empty_for_any_fault(self):
        leftover = {'c1': {'chunk_id': 'c1', 'content': '个人信息收集与使用说明。',
                           'heading': '隐私', 'title': '隐私'}}
        result = controller_fallback_result(
            'tool_call_limit', citations=leftover, utterance='全国包邮次日吗')
        self.assertEqual(result['answer'], EMPTY_EVIDENCE_ANSWER)
        self.assertEqual(result['citations'], [])
        self.assertEqual(result['fallback_empty_reason'], 'uncovered_visible_leftovers')

    def test_third_search_is_empty_observation_when_leftovers_miss_the_question(self):
        missing = {'retrieval_calls': 2, 'visible_citations': [
            {'content': '退货与订单规则。', 'heading': '政策', 'title': '政策'}]}
        covering = {'retrieval_calls': 2, 'visible_citations': [
            {'content': '政策回答提供文档版本和原文位置。', 'heading': '引用', 'title': '引用'}]}
        early = {'retrieval_calls': 1, 'visible_citations': missing['visible_citations']}
        self.assertEqual(retrieval_budget_action(missing, '依据的版本和原文'), 'empty_observation')
        self.assertEqual(retrieval_budget_action(covering, '依据的版本和原文'), 'raise_rewrite_limit')
        self.assertEqual(retrieval_budget_action(early, '依据的版本和原文'), 'search')
        data = rejected_search_data('店铺政策说明', exhausted=True)
        self.assertTrue(keep_uncovered_leftovers(data))
        self.assertTrue(data['empty_visible_evidence'])
        self.assertFalse(keep_uncovered_leftovers(rejected_search_data('店铺政策说明')))

    def test_store_policy_gap_needs_no_unrelated_citation(self):
        uncovered = {'retrieval_calls': 2, 'visible_citations': [
            {'content': '退货与订单规则。', 'heading': '政策', 'title': '政策'}]}
        covering = {'retrieval_calls': 2, 'visible_citations': [
            {'content': '政策回答提供文档版本和原文位置。', 'heading': '引用', 'title': '引用'}]}
        unseen = {'retrieval_calls': 1, 'visible_citations': [
            {'content': '个人信息收集与使用说明。', 'heading': '隐私', 'title': '隐私'}]}
        self.assertTrue(store_policy_allows_empty_citations(uncovered, '依据的版本和原文'))
        self.assertFalse(store_policy_allows_empty_citations(covering, '依据的版本和原文'))
        self.assertTrue(store_policy_allows_empty_citations(unseen, '全国包邮次日吗'))
        self.assertFalse(store_policy_allows_empty_citations({}, '依据的版本和原文'))
        self.assertTrue(store_policy_allows_empty_citations(
            {'legal_empty_visible': True, 'retrieval_calls': 1, 'visible_citations': []},
            '依据的版本和原文'))

    def test_empty_visible_flag_is_named_in_the_observation(self):
        observation = knowledge_observation({
            'answer_status': 'insufficient', 'citations': [],
            'retrieval': {'empty_visible_evidence': True}})
        self.assertTrue(observation['empty_visible_evidence'])
        self.assertEqual(observation['evidence_status'], 'none')

    def test_acl_denied_observation_names_title_not_body(self):
        observation = knowledge_observation({
            'answer_status': 'answered',
            'citations': [{'chunk_id': 'c', 'title': '退货', 'content': '退货与订单规则。'}],
            'acl_denied': [{'doc_id': 'internal-code', 'title': '内部核对码',
                            'content': 'SECRET_MARKER_SHOULD_NOT_APPEAR'}]})
        self.assertEqual(observation['acl_denied'],
                         [{'doc_id': 'internal-code', 'title': '内部核对码'}])
        self.assertNotIn('SECRET_MARKER_SHOULD_NOT_APPEAR', canonical(observation))
        self.assertEqual(observation['citations'][0]['content'], '退货与订单规则。')


class ConstraintRerankTests(unittest.TestCase):
    def test_utterance_constraints_outrank_theme_only_policy(self):
        theme = chunk('theme', '店铺政策说明', '本店退货与订单规则。没有统一承诺。')
        citation = chunk('cite', '引用规则', '政策回答提供文档版本和原文位置，可核对来源。')
        utterance = '答复能否核对来源版本'
        model_query = '店铺政策说明'
        ranked, metadata = rank_chunks(
            [theme, citation], compose_search_query(utterance, model_query),
            utterance=utterance, model_query=model_query)
        self.assertEqual(ranked[0]['doc_id'], 'cite')
        from smartlect.knowledge import RERANK_VERSION
        self.assertEqual(metadata['rerank_version'], RERANK_VERSION)
        self.assertEqual(metadata['model_query'], model_query)
        self.assertEqual(metadata['submitted_query'], model_query)
        extra = constraint_terms(utterance, model_query)
        self.assertTrue(extra)


if __name__ == '__main__':
    unittest.main()
