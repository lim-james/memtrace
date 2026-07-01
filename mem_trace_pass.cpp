#include "llvm/IR/Function.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/PassManager.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/InstIterator.h"
#include "llvm/Passes/PassPlugin.h"
#include "llvm/Passes/PassBuilder.h"

#include <cstdint>
#include <string>

class MemTracePass : public llvm::PassInfoMixin<MemTracePass> {
public:

    llvm::PreservedAnalyses run(llvm::Function& fn, llvm::FunctionAnalysisManager&) {
        if (fn.isDeclaration()) return llvm::PreservedAnalyses::all();

        const llvm::DataLayout& data_layout = fn.getParent()->getDataLayout();
        llvm::FunctionCallee mt_access_fn = get_mt_access_fn(fn);

        for (auto &instr: llvm::instructions(fn)) {
            llvm::Value*   address_ptr{};
            llvm::TypeSize size = llvm::TypeSize::getFixed(0);
            std::int8_t    is_write{};

            if (auto* load_inst = llvm::dyn_cast<llvm::LoadInst>(&instr)) {
                llvm::Type* type = load_inst->getType();
                if (!type->isSized() || type->isVoidTy()) continue;

                address_ptr = load_inst->getPointerOperand();
                size        = data_layout.getTypeStoreSize(type);
                is_write    = 0;
            } else if (auto* store_inst = llvm::dyn_cast<llvm::StoreInst>(&instr)) {
                llvm::Type* type = store_inst->getValueOperand()->getType();
                if (!type->isSized() || type->isVoidTy()) continue;

                address_ptr = store_inst->getPointerOperand();
                size        = data_layout.getTypeStoreSize(type);
                is_write    = 1;
            } else {
                continue;
            }

            llvm::IRBuilder builder{&instr};
            llvm::Value* args[] = {
                builder.CreateGlobalString(fn.getName()),
                address_ptr,
                builder.getInt32(size),
                builder.getInt8(is_write)
            };
            builder.CreateCall(mt_access_fn, args);
        }


        return llvm::PreservedAnalyses::all();
    }

    static bool isRequired() { return true; }

private:

    llvm::FunctionCallee get_mt_access_fn(llvm::Function& fn) const {
        llvm::LLVMContext& context = fn.getContext();
        auto* module = fn.getParent();

        llvm::FunctionType* mt_access_type = llvm::FunctionType::get(
            llvm::Type::getVoidTy(context), 
            {
                llvm::PointerType::get(context, 0), // char*    function_name 
                llvm::PointerType::get(context, 0), // void*    addr
                llvm::Type::getInt32Ty(context),    // uint32_t size
                llvm::Type::getInt8Ty(context)      // uint8_t  is_write
            },
            false
        );
        return module->getOrInsertFunction("__mt_access", mt_access_type);
    }

};

llvm::PassPluginLibraryInfo getMemTracePassPlugin() {
    return {
        LLVM_PLUGIN_API_VERSION, "MemTrace", "0.1",
        [](llvm::PassBuilder& pass_builder) {
            pass_builder.registerOptimizerLastEPCallback(
                [](llvm::ModulePassManager& mpm, llvm::OptimizationLevel, llvm::ThinOrFullLTOPhase) {
                    mpm.addPass(llvm::createModuleToFunctionPassAdaptor(MemTracePass{}));
                });
        }
    };
}

extern "C" LLVM_ATTRIBUTE_WEAK 
llvm::PassPluginLibraryInfo llvmGetPassPluginInfo() {
    return getMemTracePassPlugin();
}
