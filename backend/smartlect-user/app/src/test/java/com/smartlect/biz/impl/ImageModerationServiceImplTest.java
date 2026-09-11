package com.smartlect.biz.impl;

import com.smartlect.component.BaiduImageCensorComponent;
import com.smartlect.entity.dto.BaiduImageCensorResultDTO;
import com.smartlect.entity.po.ImageModerationRecord;
import com.smartlect.entity.query.ImageModerationRecordQuery;
import com.smartlect.exception.BusinessException;
import com.smartlect.mappers.ImageModerationRecordMapper;
import com.smartlect.utils.FileUtils;
import com.smartlect.utils.ImageCompressUtils;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.util.Date;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ImageModerationServiceImplTest {
    @Test
    @SuppressWarnings("unchecked")
    void ordinaryUploadsAndOrphanCleanupRemainIndependentOfRemovedQueryImages() throws Exception {
        ImageModerationServiceImpl service = new ImageModerationServiceImpl();
        FileUtils files = mock(FileUtils.class);
        BaiduImageCensorComponent censor = mock(BaiduImageCensorComponent.class);
        ImageModerationRecordMapper<ImageModerationRecord, ImageModerationRecordQuery> mapper =
                mock(ImageModerationRecordMapper.class);
        ReflectionTestUtils.setField(service, "fileUtils", files);
        ReflectionTestUtils.setField(service, "baiduImageCensorComponent", censor);
        ReflectionTestUtils.setField(service, "imageModerationRecordMapper", mapper);
        ReflectionTestUtils.setField(service, "orphanUploadHours", 24);

        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(2, 2, BufferedImage.TYPE_INT_RGB), "png", bytes);
        MockMultipartFile upload = new MockMultipartFile("file", "comment.png", "image/png", bytes.toByteArray());
        ImageCompressUtils.PreparedImage prepared = new ImageCompressUtils.PreparedImage(bytes.toByteArray(), ".png");
        when(files.prepareUploadImage(upload)).thenReturn(prepared);
        when(files.savePreparedImage(prepared, true)).thenReturn("avatar.png");
        BaiduImageCensorResultDTO result = new BaiduImageCensorResultDTO();
        result.setConclusionType(1);
        when(censor.censorImage(any(byte[].class))).thenReturn(result);
        assertEquals("avatar.png", service.uploadAndModerate(
                "user-1", "127.0.0.1", upload, true, "avatar", null).getPath());
        assertThrows(BusinessException.class, () -> service.uploadAndModerate(
                "user-1", "127.0.0.1", upload, true, "agent", null));

        result.setConclusionType(3);
        when(files.saveModerationQuarantineImage(prepared)).thenReturn("moderation/pending/comment.png");
        assertTrue(service.uploadAndModerate(
                "user-1", "127.0.0.1", upload, true, "comment", "order-1").getPendingReview());
        verify(mapper).insert(argThat(record -> "user-1".equals(record.getUserId())
                && "order-1".equals(record.getOrderId()) && "comment".equals(record.getScene())));

        ImageModerationRecord orphan = new ImageModerationRecord();
        orphan.setRecordId(7);
        orphan.setCreateTime(new Date(0));
        orphan.setImagePath("moderation/pending/orphan.png");
        when(mapper.selectList(any())).thenReturn(List.of(orphan));
        when(mapper.updateByRecordIdIfPending(any(), eq(7))).thenReturn(1, 0);
        assertEquals(1, service.cleanupOrphanedCommentUploads());
        assertEquals(0, service.cleanupOrphanedCommentUploads());
        verify(files, times(1)).deleteStoredFileQuietly("moderation/pending/orphan.png");
    }
}
