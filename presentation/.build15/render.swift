import AppKit
import PDFKit

func color(_ hex: String) -> NSColor {
    let v = UInt64(hex, radix:16) ?? 0
    return NSColor(srgbRed: CGFloat((v>>16)&255)/255, green: CGFloat((v>>8)&255)/255, blue: CGFloat(v&255)/255, alpha:1)
}
class Page: NSView {
    var model:[String:Any]=[:]
    override var isFlipped:Bool { true }
    override func draw(_ dirtyRect:NSRect) {
        color(model["background"] as! String).setFill(); bounds.fill()
        for item in model["objects"] as! [[String:Any]] {
            let r=item["rect"] as! [Double]
            var rect=NSRect(x:r[0],y:r[1],width:r[2],height:r[3])
            let kind=item["kind"] as! String
            if kind=="image" {
                if let image=NSImage(contentsOfFile:item["path"] as! String) {
                    image.draw(in:rect,from:.zero,operation:.sourceOver,fraction:1,respectFlipped:true,hints:nil)
                }
            } else {
                if kind=="cell" {color(item["fill"] as! String).setFill();rect.fill();rect=rect.insetBy(dx:7,dy:5)}
                let size=item["size"] as! Double
                let base=NSFont(name:"Arial",size:size)!
                let font=(item["bold"] as! Bool) ? NSFontManager.shared.convert(base,toHaveTrait:.boldFontMask):base
                let style=NSMutableParagraphStyle();style.lineBreakMode = .byWordWrapping
                let attrs:[NSAttributedString.Key:Any]=[.font:font,.foregroundColor:color(item["color"] as! String),.paragraphStyle:style]
                (item["text"] as! NSString).draw(with:rect,options:[.usesLineFragmentOrigin,.usesFontLeading],attributes:attrs)
            }
        }
    }
}
let root=URL(fileURLWithPath:CommandLine.arguments[1])
let data=try Data(contentsOf:root.appendingPathComponent("render_model.json"))
let models=try JSONSerialization.jsonObject(with:data) as! [[String:Any]]
let output=PDFDocument()
for (i,model) in models.enumerated() {
    let view=Page(frame:NSRect(x:0,y:0,width:960,height:540));view.model=model
    let rendered=view.dataWithPDF(inside:view.bounds)
    let single=PDFDocument(data:rendered)!
    output.insert(single.page(at:0)!,at:i)
}
let target=root.appendingPathComponent("Sudan_Rainfall_15_Slides_Illustrator.pdf")
output.write(to:target)
print(target.path)
