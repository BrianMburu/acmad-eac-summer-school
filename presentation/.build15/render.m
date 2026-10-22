#import <AppKit/AppKit.h>
#import <PDFKit/PDFKit.h>

NSColor *hexColor(NSString *hex) {
    unsigned int v=0; [[NSScanner scannerWithString:hex] scanHexInt:&v];
    return [NSColor colorWithSRGBRed:((v>>16)&255)/255.0 green:((v>>8)&255)/255.0 blue:(v&255)/255.0 alpha:1];
}
@interface SlideView : NSView
@property NSDictionary *model;
@end
@implementation SlideView
-(BOOL)isFlipped {return YES;}
-(void)drawRect:(NSRect)dirtyRect {
    [hexColor(self.model[@"background"]) setFill]; NSRectFill(self.bounds);
    for (NSDictionary *item in self.model[@"objects"]) {
        NSArray *r=item[@"rect"];
        NSRect rect=NSMakeRect([r[0] doubleValue],[r[1] doubleValue],[r[2] doubleValue],[r[3] doubleValue]);
        if ([item[@"kind"] isEqualToString:@"image"]) {
            NSImage *image=[[NSImage alloc] initWithContentsOfFile:item[@"path"]];
            [image drawInRect:rect fromRect:NSZeroRect operation:NSCompositingOperationSourceOver fraction:1 respectFlipped:YES hints:nil];
        } else {
            if ([item[@"kind"] isEqualToString:@"cell"]) { [hexColor(item[@"fill"]) setFill]; NSRectFill(rect); rect=NSInsetRect(rect,7,5); }
            NSFont *font=[NSFont fontWithName:@"Arial" size:[item[@"size"] doubleValue]];
            if ([item[@"bold"] boolValue]) font=[[NSFontManager sharedFontManager] convertFont:font toHaveTrait:NSBoldFontMask];
            NSMutableParagraphStyle *style=[NSMutableParagraphStyle new]; style.lineBreakMode=NSLineBreakByWordWrapping;
            NSDictionary *attrs=@{NSFontAttributeName:font,NSForegroundColorAttributeName:hexColor(item[@"color"]),NSParagraphStyleAttributeName:style};
            [item[@"text"] drawWithRect:rect options:NSStringDrawingUsesLineFragmentOrigin|NSStringDrawingUsesFontLeading attributes:attrs];
        }
    }
}
@end
int main(int argc,char **argv) {
 @autoreleasepool {
    NSString *root=[NSString stringWithUTF8String:argv[1]];
    NSData *data=[NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:@"render_model.json"]];
    NSArray *models=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    PDFDocument *output=[PDFDocument new];
    NSUInteger i=0;
    for (NSDictionary *model in models) {
        SlideView *view=[[SlideView alloc] initWithFrame:NSMakeRect(0,0,960,540)]; view.model=model;
        NSData *pdf=[view dataWithPDFInsideRect:view.bounds];
        PDFDocument *page=[[PDFDocument alloc] initWithData:pdf];
        [output insertPage:[page pageAtIndex:0] atIndex:i++];
    }
    NSString *target=[root stringByAppendingPathComponent:@"Sudan_Rainfall_15_Slides_Illustrator.pdf"];
    if (![output writeToFile:target]) return 1;
    printf("%s\n",target.UTF8String);
 }
 return 0;
}
