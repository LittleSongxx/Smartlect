package com.smartlect.config;

import org.springframework.cloud.loadbalancer.annotation.LoadBalancerClients;
import org.springframework.context.annotation.Configuration;

@Configuration
@LoadBalancerClients(defaultConfiguration = SmartlectLoadBalancerClientConfiguration.class)
public class SmartlectLoadBalancerAutoConfiguration {
}
