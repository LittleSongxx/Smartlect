package com.smartlect.cloud;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;
import org.springframework.cloud.openfeign.EnableFeignClients;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.context.annotation.FullyQualifiedAnnotationBeanNameGenerator;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableDiscoveryClient
@EnableFeignClients(basePackages = "com.smartlect.api", defaultConfiguration = com.smartlect.api.feign.SmartlectFeignConfiguration.class)
@ComponentScan(basePackages = "com.smartlect", nameGenerator = FullyQualifiedAnnotationBeanNameGenerator.class)
@MapperScan("com.smartlect.mappers")
@EnableScheduling
public class SmartlectAdminApplication {
    public static void main(String[] args) {
        SpringApplication.run(SmartlectAdminApplication.class, args);
    }
}
