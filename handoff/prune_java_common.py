"""One-time P0 edits of inspected legacy-only dependency chains."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1] / 'backend'
common = root / 'smartlect-common'

def edit(path, fn):
    body = path.read_text()
    path.write_text(fn(body))

def cut(body, start, end):
    a, b = body.index(start), body.index(end, body.index(start))
    return body[:a] + body[b:]

# These types/resources only served the omitted search and conversation modules.
for suffix in ('main/java/com/smartlect/entity/dto/RagDataDTO.java',
               'main/java/com/smartlect/entity/vo/RagSyncFailureVO.java',
               'main/java/com/smartlect/entity/enums/RagDataTypeEnum.java',
               'main/java/com/smartlect/entity/enums/PromptTypeEnum.java',
               'test/java/com/smartlect/entity/enums/RagDataTypeEnumTest.java'):
    (common / 'src' / suffix).unlink()
for path in (common / 'src/main/resources/prompt').glob('*'):
    path.unlink()
edit(common / 'pom.xml', lambda s: re.sub(r'\s*<dependency>\s*<groupId>org.springframework.boot</groupId>\s*<artifactId>spring-boot-starter-data-elasticsearch</artifactId>\s*</dependency>', '', s))

base = common / 'src/main/java/com/smartlect'
edit(base / 'component/RedisComponent.java', lambda s: cut(cut(cut(cut(s,
     '    private static String cancelAgentMessageRedisKey', '    // 签到读写'),
     '    public void addRagFailRecord', '    public void deleteCacheKey'),
     '    private static String ensureAgentConsultPayloadUserId', '    public boolean setIfAbsent'),
     'import com.fasterxml.jackson.databind.node.ObjectNode;', 'import jakarta.annotation.Resource;')
     .replace('"member:level:claim:"', 'Constants.REDIS_KEY_PREFIX + "member:level:claim:"'))
edit(base / 'entity/config/AppConfig.java', lambda s: re.sub(r'    @Value\("\$\{project.ai-chat-limit:0}\"\)\s*private Integer aiChatLimit;\n', '', s).replace('    public Integer getAiChatLimit() {\n        return aiChatLimit;\n    }\n', ''))
edit(base / 'constants/Constants.java', lambda s: '\n'.join(line for line in s.split('\n') if not any(key in line for key in ('REDIS_RAG_FAIL_RECORD', 'REDIS_KEY_CANCEL_AGENT_MESSAGE', 'REDIS_KEY_PROMPT', 'REDIS_KEY_AGENT_', 'WS_MESSAGE_TOPIC_AGENT', '//向量数据库', '//提示词'))))
edit(base / 'constants/RabbitMQConfig.java', lambda s: '\n'.join(line for line in cut(s, '    // Rag交换机', '    // ========== 通知队列').split('\n') if 'RAG_' not in line and '// Rag' not in line))
edit(base / 'support/MqConsumeReplayRouter.java', lambda s: re.sub(r'            case RabbitMQConfig.RAG_.*?;\n', '', s, flags=re.S))
edit(base / 'service/impl/MqCompensationLogServiceImpl.java', lambda s: s.replace('        if (key.contains("rag")) {\n            return "RAG";\n        }\n', ''))
edit(base / 'entity/query/MqCompensationLogQuery.java', lambda s: cut(s, '    private Boolean ragRelatedOnly;', '    public Integer getLogId()'))
edit(common / 'src/main/resources/com/smartlect/mappers/MqCompensationLogMapper.xml', lambda s: re.sub(r'\s*<if test="query.ragRelatedOnly.*?</if>', '', s, flags=re.S))

# All queue, exchange and routing names belong to this installation.
mq = base / 'constants/RabbitMQConfig.java'
body = mq.read_text()
names = re.findall(r'public static final String \w+ = "([^"]+)";', body)
for path in [p for mod in root.iterdir() if mod.is_dir() and mod.name not in ('smartlect-admin', 'smartlect-user', 'smartlect-product') for p in mod.rglob('*') if p.is_file()]:
    if path.suffix not in ('.java', '.xml', '.yml', '.sql'):
        continue
    def rename(s):
        for name in names:
            if not name.startswith('smartlect.'):
                s = s.replace('"' + name + '"', '"smartlect.' + name + '"')
        for old, new in [('AgentDelegatedIdentity','DelegatedUserIdentity'), ('AGENT_USER_ID','DELEGATED_USER_ID'),
                         ('X-Agent-User-Id','X-Smartlect-User-Id'), ('prepareAgentImage','prepareUserImage'),
                         ('OrderAgentInternalController','OrderCommerceInternalController'),
                         ('CouponAgentInternalController','CouponCommerceInternalController'),
                         ('AgentActionStatusService','CommerceActionStatusService'),
                         ('agentActionStatusService','commerceActionStatusService'),
                         ('AgentActionIdempotencySurfaceTest','CommerceActionIdempotencySurfaceTest'),
                         ('/order/agent','/order/commerce'),('/coupon/agent','/coupon/commerce'),
                         ('smartlect.agent.', 'smartlect.growth.'), ('agentBaseUrl','growthBaseUrl'),
                         ('http://127.0.0.1:7050', 'http://127.0.0.1:18000')]:
            s = s.replace(old,new)
        return s
    edit(path, rename)
    renamed = rename(path.name)
    if renamed != path.name:
        path.rename(path.with_name(renamed))

gateway = root / 'smartlect-gateway/src/main'
edit(gateway / 'resources/application.yml', lambda s: re.sub(r'            - id: (agent-http|agent-ws|internal-search|admin-search|search)\n.*?(?=            - id:|\nsmartlect:)', '', s, flags=re.S).replace('      agent-send-qps: 10\n','').replace('        - /api/search/loadHotKeywords\n','').replace('        - /api/search/products\n',''))
config = gateway / 'java/com/smartlect/cloud/gateway/config'
edit(config / 'SentinelGatewayConfig.java', lambda s: cut(cut(cut(cut(s,
    '        // 降级规则：Agent', '        if (!rateLimitProperties'),
    '    /**\n     * 为 Python Agent', '    private void initCustomApis'),
    '        // Agent 发消息接口', '        GatewayApiDefinitionManager'),
    '        // agent-send：', '        for (String routeId')
    .replace('        double agentSendQps = rateLimitProperties.getAgentSendQps();\n','')
    .replace('"search", "stock", "admin", "agent-http", "agent-ws"','"stock", "admin-bff"'))
edit(config / 'GatewayRateLimitProperties.java', lambda s: cut(cut(s, '    /** 单 IP', '    public boolean'), '    public double getAgentSendQps()', '}\n' if False else '    public void setAgentSendQps').replace('    public void setAgentSendQps(double agentSendQps) {\n        this.agentSendQps = agentSendQps;\n    }\n', ''))

it = common / 'src/test/java/com/smartlect/middleware/MiddlewareIT.java'
edit(it, lambda s: cut(cut(cut(s,
    '    private static final String DEFAULT_ELASTICSEARCH_IMAGE', '    @Container'),
    '    @Container\n    static final GenericContainer<?> ELASTICSEARCH', '    @Test'),
    '    @Test\n    void elasticsearchAcceptsTheSingleEmbeddingContract', '    private static Connection mysqlConnection')
    .replace('assertEquals(9, migrations.size()', 'assertEquals(8, migrations.size()')
    .replace('root.resolve("smartlect-search")','root.resolve("smartlect-common")')
    .replace('                "smartlect-search/src/main/resources/db/migration/R__current_schema.sql",\n',''))
print('Pruned common/gateway legacy-only AI dependencies; preserved transaction and identity flows')
