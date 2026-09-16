package com.smartlect.utils;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * 读取路径的双向回退：展示大图的前端会把 _thumbnail 从路径里去掉再请求，而只存了缩略图的
 * 商品（历史种子数据就是这样）原图并不存在；反过来只存原图的路径也会被请求成缩略图。
 */
class FileUtilsThumbnailFallbackTest {

    @Test
    void readableCandidatesCoverBothDirectionsAndKeepOrder() {
        assertEquals(List.of("202601/a.png", "202601/a_thumbnail.png"),
                FileUtils.readableCandidates("202601/a.png"));
        assertEquals(List.of("202601/a_thumbnail.png", "202601/a.png"),
                FileUtils.readableCandidates("202601/a_thumbnail.png"));
    }

    @Test
    void readableCandidatesKeepAnUnknownPathAsTheOnlyCandidate() {
        assertEquals(List.of("202601/a"), FileUtils.readableCandidates("202601/a"));
        assertEquals(List.of("202601/a.png"), FileUtils.readableCandidates("202601/a.png").subList(0, 1));
        assertEquals(List.of(), FileUtils.readableCandidates(null));
        assertEquals(List.of(), FileUtils.readableCandidates(""));
    }

    @Test
    void fromThumbnailRelativePathIsTheInverseOfToThumbnailRelativePath() {
        String original = "2026-06/g9amuJeHC4mIPMgdQNbMk5FZ6LpBEW.png";
        String thumbnail = FileUtils.toThumbnailRelativePath(original);
        assertEquals("2026-06/g9amuJeHC4mIPMgdQNbMk5FZ6LpBEW_thumbnail.png", thumbnail);
        assertEquals(original, FileUtils.fromThumbnailRelativePath(thumbnail));
        assertNull(FileUtils.fromThumbnailRelativePath(original));
        assertNull(FileUtils.toThumbnailRelativePath(thumbnail));
        assertNull(FileUtils.fromThumbnailRelativePath(null));
        // 没有后缀的路径无法安全改写，两个方向都返回 null 而不是猜一个文件名
        assertNull(FileUtils.fromThumbnailRelativePath("2026-06/a_thumbnail"));
        assertNull(FileUtils.toThumbnailRelativePath("2026-06/a"));
    }

    @Test
    void readableCandidatesNeverRepeatTheSamePath() {
        // 没有后缀时两个方向都返回 null，候选里只应留下原样路径
        assertEquals(List.of("a_thumbnail"), FileUtils.readableCandidates("a_thumbnail"));
    }
}
