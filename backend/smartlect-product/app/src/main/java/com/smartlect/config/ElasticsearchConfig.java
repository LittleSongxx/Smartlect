package com.smartlect.config;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.json.jackson.JacksonJsonpMapper;
import co.elastic.clients.transport.rest_client.RestClientTransport;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.http.HttpHost;
import org.apache.http.message.BasicHeader;
import org.elasticsearch.client.RestClient;
import org.elasticsearch.client.RestClientBuilder;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.nio.charset.StandardCharsets;
import java.util.Base64;

/**
 * 商品搜索 ES 客户端（与 deploy 容器同版本 8.19）。
 *
 * <p>安全关闭的本地集群：url 直连、无凭据；api-key 非空时以 Authorization 头携带
 * （与 assistant 侧 SMARTLECT_ES_* 环境变量同源）。客户端构建是惰性连接，ES 暂不可达
 * 不阻塞启动——查询方对 IOException 做降级（回退 SQL LIKE）。</p>
 */
@Configuration
public class ElasticsearchConfig {

    @Bean(destroyMethod = "close")
    public RestClient elasticsearchRestClient(
            @Value("${smartlect.es.url}") String url,
            @Value("${smartlect.es.api-key:}") String apiKey,
            ObjectMapper objectMapper) {
        RestClientBuilder builder = RestClient.builder(HttpHost.create(url));
        if (!apiKey.isBlank()) {
            String token = Base64.getEncoder().encodeToString(
                    (":" + apiKey).getBytes(StandardCharsets.UTF_8));
            builder.setDefaultHeaders(new BasicHeader[]{new BasicHeader("Authorization", "Basic " + token)});
        }
        return builder.build();
    }

    @Bean
    public ElasticsearchClient elasticsearchClient(RestClient restClient, ObjectMapper objectMapper) {
        return new ElasticsearchClient(
                new RestClientTransport(restClient, new JacksonJsonpMapper(objectMapper)));
    }
}
