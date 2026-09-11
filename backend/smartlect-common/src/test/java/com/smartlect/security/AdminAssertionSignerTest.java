package com.smartlect.security;

import com.smartlect.entity.dto.AdminPrincipalDTO;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AdminAssertionSignerTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(AdminAssertionSigner.class)
            .withPropertyValues(
                    "smartlect.admin-assertion.current-secret=test-secret",
                    "smartlect.admin-assertion.current-key-id=test-key");

    @Test
    void createsSignerFromConfiguredConstructor() {
        contextRunner.run(context -> {
            assertThat(context).hasSingleBean(AdminAssertionSigner.class);

            AdminPrincipalDTO principal = new AdminPrincipalDTO();
            principal.setAdminId("admin-1");
            principal.setAccount("operator");

            assertThat(context.getBean(AdminAssertionSigner.class)
                    .sign("GET", "/internal/test", null, principal))
                    .containsEntry("X-Admin-Id", "admin-1")
                    .containsEntry("X-Admin-Key-Id", "test-key")
                    .containsKeys("X-Admin-Timestamp", "X-Admin-Nonce", "X-Admin-Signature");
        });
    }

    @Test
    void internalServiceTokenCannotSubstituteForAnAssertionSecret() {
        new ApplicationContextRunner().withUserConfiguration(AdminAssertionSigner.class)
                .withPropertyValues("smartlect.internal.token=internal-only")
                .run(context -> {
                    AdminPrincipalDTO principal = new AdminPrincipalDTO();
                    principal.setAdminId("admin-1");
                    assertThatThrownBy(() -> context.getBean(AdminAssertionSigner.class)
                            .sign("POST", "/internal/test", null, principal))
                            .isInstanceOf(IllegalStateException.class)
                            .hasMessageContaining("独立");
                });
    }
}
