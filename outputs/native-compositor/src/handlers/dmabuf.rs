//! Validate client GPU buffers with the same renderer that composites them.
use crate::Smallvil;
use smithay::{backend::allocator::dmabuf::Dmabuf, wayland::dmabuf::{DmabufGlobal,DmabufHandler,DmabufState,ImportNotifier}};
impl DmabufHandler for Smallvil {
    fn dmabuf_state(&mut self)->&mut DmabufState {&mut self.dmabuf_state}
    fn dmabuf_imported(&mut self,_global:&DmabufGlobal,buffer:Dmabuf,notifier:ImportNotifier) {
        if self.dmabuf_importer.as_mut().is_some_and(|import|import(&buffer)) {
            let _=notifier.successful::<Self>();
        } else {notifier.failed();}
    }
}
smithay::delegate_dmabuf!(Smallvil);
