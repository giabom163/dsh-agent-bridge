# B1 UI 修复说明

## 根因
`web/style.css` 中 `.graph-error,.graph-empty{display:grid}` 的类选择器特异性高于浏览器默认 `[hidden]{display:none}`，因此 JS 里 `hidden=true`（如空态）时元素 computed display 仍为 `grid`，绝对定位覆盖在画布上，遮挡十个任务按钮与三个 canvas。

## 改动
`web/style.css` 仅新增一条作用域规则：

```
.graph-empty[hidden],.graph-error[hidden]{display:none}
```

使其 `hidden` 真正不显示；未触碰其他样式，未改 JS/API/内核/依赖/配置。

## 未实机项
本机未启动服务、未跑浏览器，修复未做真机验证。真机验收由主线程执行；本文档不给出最终 PASS。
