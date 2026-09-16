package com.smartlect.controller;

import com.smartlect.entity.config.AppConfig;
import com.smartlect.utils.FileUtils;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.util.ReflectionTestUtils;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * {@code /getResource} 的行为契约：只存了另一个变体时回退到存在的那一个；真的缺失时回 404
 * 而不是 200 空体——空体带 {@code max-age=100000} 会被浏览器缓存近一天，正是"大图一直
 * 加载不出来"的直接原因。用户端与管理端两个 FileController 用的是同一套语义。
 */
class FileControllerResourceTest {

    @TempDir
    Path tempDir;

    private final FileUtils fileUtils = new FileUtils();
    private final MockHttpServletResponse response = new MockHttpServletResponse();
    private final byte[] thumbnailBytes = "thumbnail-bytes".getBytes();

    @BeforeEach
    void setUp() throws Exception {
        AppConfig appConfig = mock(AppConfig.class);
        when(appConfig.getProjectFolder()).thenReturn(tempDir.toString() + "/");
        ReflectionTestUtils.setField(fileUtils, "appConfig", appConfig);
        Path stored = tempDir.resolve("file/202601/only-thumbnail_thumbnail.png");
        Files.createDirectories(stored.getParent());
        Files.write(stored, thumbnailBytes);
    }

    private FileController userController() {
        FileController controller = new FileController();
        ReflectionTestUtils.setField(controller, "fileUtils", fileUtils);
        return controller;
    }

    private com.smartlect.controller.admin.FileController adminController() {
        com.smartlect.controller.admin.FileController controller =
                new com.smartlect.controller.admin.FileController();
        ReflectionTestUtils.setField(controller, "fileUtils", fileUtils);
        return controller;
    }

    @Test
    void originalRequestFallsBackToTheStoredThumbnailVariant() throws Exception {
        // 商品图只存了缩略图、详情页大图请求去掉 _thumbnail 的原图：必须回退到实际存在的文件
        userController().getResource(response, "202601/only-thumbnail.png");
        assertEquals(200, response.getStatus());
        assertArrayEquals(thumbnailBytes, response.getContentAsByteArray());

        MockHttpServletResponse adminResponse = new MockHttpServletResponse();
        adminController().getResource(adminResponse, "202601/only-thumbnail.png");
        assertEquals(200, adminResponse.getStatus());
        assertArrayEquals(thumbnailBytes, adminResponse.getContentAsByteArray());
    }

    @Test
    void thumbnailRequestStillFallsBackToTheOriginalVariant() throws Exception {
        byte[] originalBytes = "original-bytes".getBytes();
        Path original = tempDir.resolve("file/202601/only-original.png");
        Files.write(original, originalBytes);

        userController().getResource(response, "202601/only-original_thumbnail.png");
        assertEquals(200, response.getStatus());
        assertArrayEquals(originalBytes, response.getContentAsByteArray());
    }

    @Test
    void missingFileIsNotFoundWithoutCacheHeader() throws Exception {
        userController().getResource(response, "202601/absent.png");
        assertEquals(404, response.getStatus());
        assertEquals(0, response.getContentAsByteArray().length);
        // 空响应绝不能再带长缓存：那正是破图被缓存近一天的原因
        assertTrue(response.getHeader("Cache-Control") == null);

        MockHttpServletResponse adminResponse = new MockHttpServletResponse();
        adminController().getResource(adminResponse, "202601/absent.png");
        assertEquals(404, adminResponse.getStatus());
        assertEquals(0, adminResponse.getContentAsByteArray().length);
    }

    @Test
    void traversalPathIsRejected() throws Exception {
        userController().getResource(response, "../../etc/passwd");
        assertEquals(404, response.getStatus());
        assertEquals(0, response.getContentAsByteArray().length);
    }
}
