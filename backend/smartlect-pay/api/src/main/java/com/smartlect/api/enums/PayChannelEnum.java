package com.smartlect.api.enums;

import java.util.Arrays;
import java.util.Optional;

public enum PayChannelEnum {
    MOCK("mock", "mock", "payChannel4Mock", "Smartlect 模拟支付");

    private String payChannel;
    private String payScene;
    private String beanName;
    private String desc;

    PayChannelEnum(String payChannel, String payScene, String beanName, String desc) {
        this.payChannel = payChannel;
        this.payScene = payScene;
        this.beanName = beanName;
        this.desc = desc;
    }

    public String getPayChannel() {
        return payChannel;
    }

    public String getPayScene() {
        return payScene;
    }

    public String getBeanName() {
        return beanName;
    }

    public String getDesc() {
        return desc;
    }

    public static PayChannelEnum getByPayScene(String payScene) {
        if (payScene == null || payScene.isEmpty()) {
            return null;
        }
        Optional<PayChannelEnum> typeEnum = Arrays.stream(PayChannelEnum.values())
                .filter(value -> value.getPayScene().equals(payScene))
                .findFirst();
        return typeEnum.orElse(null);
    }

    public static PayChannelEnum resolve(String payChannelOrScene) {
        if (payChannelOrScene == null || payChannelOrScene.isEmpty()) {
            return null;
        }
        PayChannelEnum byScene = getByPayScene(payChannelOrScene);
        if (byScene != null) {
            return byScene;
        }
        return Arrays.stream(PayChannelEnum.values())
                .filter(value -> value.getPayChannel().equals(payChannelOrScene))
                .findFirst()
                .orElse(null);
    }
}
