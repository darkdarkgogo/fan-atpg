// Original Verilog/library bridge to the original FAN multiple-backtrace target solver.
#include "atpg.h"
#include "interface/techlib_builder.h"
#include "interface/netlist_builder.h"
#include <memory>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <queue>
#include <random>
#include <unordered_map>
#include <unordered_set>
namespace py = pybind11;
using namespace CoreNs;
namespace CoreNs {
class FanNativeAccess {
public:
  static void setup(Atpg &a) { a.setupCircuitParameter(); }
  static int solve(Atpg &a, Fault f, bool dtc, int limit) {
    a.clearAllEvents();
    a.nativeBacktrackLimit_ = limit;
    return a.generateSinglePatternOnTargetFault(f, dtc);
  }
  static int backtracks(Atpg &a) { return a.nativeLastBacktracks_; }
  static void good(Atpg &a) { a.clearAllFaultEffectByEvaluation(); }
};
} // namespace CoreNs
static const char *kind_name(Gate::GateType t) {
  static const char *names[] = {"NA","PI","PO","PPI","PPO","PPI_IN","PPO_IN",
    "INV","BUF","AND2","AND3","AND4","NAND2","NAND3","NAND4",
    "OR2","OR3","OR4","NOR2","NOR3","NOR4","XOR2","XOR3","XNOR2","XNOR3",
    "MUX","TIE0","TIE1","TIEX","TIEZ"};
  return int(t)>=0 && int(t)<30 ? names[int(t)] : "NA";
}
// The original parser/build objects own raw cells. Free each allocation once;
// ports and nets hold non-owning graph edges and libc_ is a shared reference.
static void destroy_cell(IntfNs::Cell *cell) {
  for (size_t i=0;i<cell->getNCell();++i) destroy_cell(cell->getCell(i));
  for (size_t i=0;i<cell->getNPort();++i) delete cell->getPort(i);
  for (size_t i=0;i<cell->getNNet();++i) delete cell->getNet(i);
  delete cell;
}
struct OwnedTechlib : IntfNs::Techlib {
  ~OwnedTechlib() { for(size_t i=0;i<getNCell();++i) destroy_cell(getCell(i)); }
};
struct OwnedNetlist : IntfNs::Netlist {
  ~OwnedNetlist() { for(size_t i=0;i<getNModule();++i) destroy_cell(getModule(i)); }
};
struct NativeCircuit {
  OwnedTechlib lib;
  OwnedNetlist nl;
  Circuit c;
  std::vector<std::string> names, inputs, outputs, humanNames;
  std::vector<int> stateInputs, stateOutputs;
  std::vector<std::string> scanChain;
  int physicalPI=0, physicalPO=0;
  static void check_acyclic(IntfNs::Cell *top, IntfNs::Techlib *lib=nullptr) {
    std::vector<int> indegree(top->getNCell(),0);
    std::vector<std::vector<int>> edges(top->getNCell());
    for (size_t i=0;i<top->getNCell();++i)
      for (auto dst:top->getFanout(i)) {
        if(lib && lib->hasPmt(dst->libc_->id_,IntfNs::Pmt::DFF)) continue;
        edges[i].push_back(dst->id_); ++indegree[dst->id_];}
    std::queue<int> q; for(size_t i=0;i<indegree.size();++i) if(!indegree[i]) q.push(i);
    size_t count=0; while(!q.empty()){int i=q.front();q.pop();++count;
      for(int j:edges[i]) if(!--indegree[j]) q.push(j);}
    if(count!=indegree.size()) throw std::invalid_argument("unsupported combinational cycle");
  }
  int netkey(IntfNs::Net *net) const {
    if(!net) throw std::invalid_argument("unsupported unconnected scan pin");
    int key=net->id_; for(auto n:nl.getTop()->getEqvNets(net->id_)) key=std::min(key,n->id_);
    return key;
  }
  void validate_scan(IntfNs::Cell *top) {
    std::vector<IntfNs::Cell *> ffs;
    for(size_t i=0;i<top->getNCell();++i) {
      auto cell=top->getCell(i);
      if(cell->libc_ && lib.hasPmt(cell->libc_->id_,IntfNs::Pmt::DFF)) ffs.push_back(cell);
    }
    if(ffs.empty()) return;
    for(auto name:{"CK","test_si","test_se","test_so"}) {
      auto port=top->getPort(name);
      if(!port || port->type_!=(std::string(name)=="test_so"?IntfNs::Port::OUTPUT:IntfNs::Port::INPUT))
        throw std::invalid_argument("unsupported fullscan boundary ports");
    }
    const int ck=netkey(top->getPort("CK")->inNet_), se=netkey(top->getPort("test_se")->inNet_);
    std::unordered_map<int,IntfNs::Cell *> chain;
    for(auto ff:ffs) {
      std::string type=ff->libc_->name_;
      const std::unordered_set<std::string> allowed={"SDFF_X1","SDFF_X2","SDFFR_X1","SDFFR_X2","SDFFS_X1","SDFFS_X2","SDFFRS_X1","SDFFRS_X2"};
      if(!allowed.count(type)) throw std::invalid_argument("unsupported non-scan flip-flop");
      for(auto name:{"CK","SE","SI","D","Q"})
        if(!ff->getPort(name) || !ff->getPort(name)->exNet_) throw std::invalid_argument("unsupported incomplete scan FF");
      if(netkey(ff->getPort("CK")->exNet_)!=ck || netkey(ff->getPort("SE")->exNet_)!=se)
        throw std::invalid_argument("unsupported scan clock or enable");
      auto qn=ff->getPort("QN");
      if(qn && qn->exNet_) throw std::invalid_argument("unsupported connected FF QN; use explicit inverter on Q");
      for(auto name:{"RN","SN"}) {
        auto pin=ff->getPort(name); if(!pin) continue;
        bool high=false;
        for(auto net:top->getEqvNets(netkey(pin->exNet_))) for(size_t j=0;j<net->getNPort();++j) {
          auto p=net->getPort(j);
          if(p->top_!=top && p->type_==IntfNs::Port::OUTPUT && std::string(p->top_->libc_->name_)=="LOGIC1_X1") high=true;
        }
        if(!high) throw std::invalid_argument("unsupported active/variable async control; tie RN/SN inactive for capture");
      }
      if(!chain.emplace(netkey(ff->getPort("SI")->exNet_),ff).second)
        throw std::invalid_argument("unsupported branched scan chain");
    }
    int next=netkey(top->getPort("test_si")->inNet_);
    std::unordered_set<IntfNs::Cell *> seen;
    while(chain.count(next)) {
      auto ff=chain.at(next);
      if(!seen.insert(ff).second) throw std::invalid_argument("unsupported cyclic scan chain");
      scanChain.push_back(ff->name_); next=netkey(ff->getPort("Q")->exNet_);
    }
    if(seen.size()!=ffs.size() || next!=netkey(top->getPort("test_so")->inNet_))
      throw std::invalid_argument("unsupported disconnected scan chain");
    // Clock/shift controls cannot participate in functional data logic.
    for(auto name:{"CK","test_si","test_se"}) for(auto n:top->getEqvNets(netkey(top->getPort(name)->inNet_)))
      for(size_t j=0;j<n->getNPort();++j) {
        auto p=n->getPort(j); if(p==top->getPort(name)) continue;
        std::string pin=p->name_;
        if(p->top_==top || !seen.count(p->top_) ||
           pin!=(std::string(name)=="CK"?"CK":std::string(name)=="test_se"?"SE":"SI"))
          throw std::invalid_argument("unsupported scan control used as functional data");
      }
  }
  NativeCircuit(const std::string &path, const std::string &library) {
    if(library.empty()) throw std::invalid_argument("library_path is required for FAN Verilog");
    std::string lower=path; std::transform(lower.begin(),lower.end(),lower.begin(),::tolower);
    if(lower.size()>=6 && lower.substr(lower.size()-6)==".bench")
      throw std::invalid_argument("BENCH input is unsupported; use structural Verilog and an MDT library");
    IntfNs::MdtLibBuilder lb(&lib);
    if(!lb.read(library.c_str(),false) || !lib.check(false))
      throw std::invalid_argument("original FAN MDT library read/check failed: "+library);
    nl.setTechlib(&lib);
    IntfNs::VlogNlBuilder nb(&nl);
    if(!nb.read(path.c_str(),false) || !nl.check(false))
      throw std::invalid_argument("original FAN Verilog netlist read/check failed: "+path);
    auto top=nl.getTop();
    if(!top) throw std::invalid_argument("Verilog has no top module");
    validate_scan(top);
    for(size_t i=0;i<top->getNPort();++i) {
      auto p=top->getPort(i); std::string name=p->name_;
      if((p->type_!=IntfNs::Port::INPUT && p->type_!=IntfNs::Port::OUTPUT) ||
         (scanChain.empty() && ((p->type_==IntfNs::Port::INPUT && (name=="CK" || name=="test_si" || name=="test_se")) ||
         (p->type_==IntfNs::Port::OUTPUT && name=="test_so"))))
        throw std::invalid_argument("unsupported port type or reserved scan/clock name: "+name);
    }
    for(size_t i=0;i<top->getNNet();++i) {
      std::unordered_set<IntfNs::Port *> drivers;
      for(auto n:top->getEqvNets(i)) for(size_t j=0;j<n->getNPort();++j) {
        auto p=n->getPort(j);
        if((p->top_==top && p->type_==IntfNs::Port::INPUT) ||
           (p->top_!=top && p->type_==IntfNs::Port::OUTPUT)) drivers.insert(p);
      }
      if(drivers.size()!=1) throw std::invalid_argument("unsupported missing or multiple net drivers");
    }
    // Reject before Circuit's mapper, whose historical TIEX mapping is TIE0.
    for(size_t i=0;i<top->getNCell();++i) {
      auto cell=top->getCell(i);
      if(!cell->libc_) throw std::invalid_argument("unsupported hierarchical Verilog cell");
      for(size_t j=0;j<cell->getNPort();++j)
        if(!cell->getPort(j)->exNet_ && !(lib.hasPmt(cell->libc_->id_,IntfNs::Pmt::DFF) && std::string(cell->getPort(j)->name_)=="QN"))
          throw std::invalid_argument("unsupported unconnected technology cell pin");
      if(lib.hasPmt(cell->libc_->id_,IntfNs::Pmt::DFF)) continue;
      for(size_t j=0;j<cell->libc_->getNCell();++j) {
        auto primitive=cell->libc_->getCell(j);
        for(size_t k=0;k<primitive->getNPort();++k)
          if(!primitive->getPort(k)->exNet_)
            throw std::invalid_argument("unsupported unconnected library primitive pin");
      }

      for(auto t:{IntfNs::Pmt::DLAT,IntfNs::Pmt::MUX,IntfNs::Pmt::TIEX,IntfNs::Pmt::TIEZ})
        if(lib.hasPmt(cell->libc_->id_,t))
          throw std::invalid_argument("unsupported sequential, MUX or constant/high-impedance primitive");
    }
    for(size_t i=0;i<lib.getNCell();++i)
      if(!lib.hasPmt(i,IntfNs::Pmt::DFF)) check_acyclic(lib.getCell(i));
    check_acyclic(top,&lib);
    if(!c.buildCircuit(&nl,1)) throw std::invalid_argument("original FAN Circuit::buildCircuit failed");
    physicalPI=c.numPI_; physicalPO=c.numPO_;
    for(auto &g:c.circuitGates_) {
      if(g.gateType_==Gate::PPI) {stateInputs.push_back(g.gateId_); g.gateType_=Gate::PI;}
      if(g.gateType_==Gate::PPO) {stateOutputs.push_back(g.gateId_); g.gateType_=Gate::PO;}
    }
    c.numPI_+=c.numPPI_; c.numPO_+=c.numPPI_; c.numPPI_=0;
    if(!c.numPI_ || !c.numPO_) throw std::invalid_argument("unsupported empty-input/output circuit");
    for(auto &g:c.circuitGates_) {
      if(!(g.gateType_==Gate::PI || g.gateType_==Gate::PO ||
           (g.gateType_>=Gate::INV && g.gateType_<=Gate::XNOR3) ||
           g.gateType_==Gate::TIE0 || g.gateType_==Gate::TIE1))
        throw std::invalid_argument(std::string("unsupported native primitive: ")+kind_name(g.gateType_));
      int arity=0;
      if(g.gateType_==Gate::PO || g.gateType_==Gate::INV || g.gateType_==Gate::BUF) arity=1;
      if(g.gateType_>=Gate::AND2 && g.gateType_<=Gate::NOR4) arity=2+(int(g.gateType_)-int(Gate::AND2))%3;
      if(g.gateType_>=Gate::XOR2 && g.gateType_<=Gate::XNOR3) arity=2+(int(g.gateType_)-int(Gate::XOR2))%2;
      if(int(g.faninVector_.size())!=arity || g.numFI_!=arity)
        throw std::invalid_argument("unsupported native primitive arity");
      names.push_back("g"+std::to_string(g.gateId_));
      if(g.gateType_==Gate::PI || g.gateType_==Gate::PO) {
        bool state=std::find(stateInputs.begin(),stateInputs.end(),g.gateId_)!=stateInputs.end() ||
                   std::find(stateOutputs.begin(),stateOutputs.end(),g.gateId_)!=stateOutputs.end();
        std::string name=state ? std::string(top->getCell(g.cellId_)->name_)+(g.gateType_==Gate::PI?"/Q":"/D") : top->getPort(g.cellId_)->name_;
        humanNames.push_back(name);
        (g.gateType_==Gate::PI ? inputs:outputs).push_back(name);
      } else {
        auto cell=top->getCell(g.cellId_);
        humanNames.push_back(std::string(cell->name_)+"/"+cell->libc_->getCell(g.primitiveId_)->name_);
      }
      for(int fi:g.faninVector_) if(fi<0 || fi>=g.gateId_)
        throw std::invalid_argument("unsupported native non-topological fanin");
    }
  }
  py::dict graph() const {
    py::dict result; py::list gates;
    std::vector<int> pi,po;
    for(auto &g:c.circuitGates_) {
      py::dict d; d["gate_id"]=g.gateId_;d["name"]=humanNames[g.gateId_];
      d["kind"]=kind_name(g.gateType_); d["fanins"]=g.faninVector_;gates.append(d);
      if(g.gateType_==Gate::PI) pi.push_back(g.gateId_);
      if(g.gateType_==Gate::PO) po.push_back(g.gateId_);
    }
    result["schema"]="fan_circuit_graph_v1";result["gates"]=gates;
    result["input_gate_ids"]=pi;result["output_gate_ids"]=po;
    result["input_names"]=inputs;result["output_names"]=outputs;
    if(!scanChain.empty()) {
      py::dict scan; scan["mode"]="fullscan_single_capture";
      scan["state_input_gate_ids"]=stateInputs; scan["next_state_output_gate_ids"]=stateOutputs;
      scan["chain_si_to_so"]=scanChain; scan["physical_pi_count"]=physicalPI; scan["physical_po_count"]=physicalPO;
      scan["async_controls"]="tied_inactive"; scan["fault_scope"]="functional_data_only";
      result["scan"]=scan;
    }
    return result;
  }
};
class Session {
  NativeCircuit b;
  FaultListExtract fl;
  std::unique_ptr<Simulator> simulator;
  std::unique_ptr<Atpg> solver;
  std::vector<std::string> ids;
  std::unordered_map<std::string, int> lookup;
  std::vector<bool> tried, detected, redundant, aborted;
  int limit, seed, primaryCalls = 0, dtcCalls = 0, primaryBT = 0, dtcBT = 0,
                   batch = 0, selected = -1;
  bool dtc, stc, active = false, finalized = false;
  std::mt19937 rng;
  std::vector<std::string> patterns, finalPatterns, attempted, embedded, newly,
      lastAttempt, lastEmbed;
  std::string cube, status, vector;
  std::vector<int> candidates;
  std::vector<bool> visited, secondaryTried;
  int currentPO = -1;
  std::queue<int> bfs;
  int shuffleAttempts = 0;
  int eval(const Gate &g, const std::vector<int> &v, int fault = -1,
           int pin = -1, int stuck = 0) const {
    std::vector<int> x;
    for (size_t j = 0; j < g.faninVector_.size(); ++j)
      x.push_back(fault == g.gateId_ && pin == int(j) ? stuck
                                                      : v[g.faninVector_[j]]);
    if (g.gateType_ == Gate::PI)
      return v[g.gateId_];
    int r = 2;
    switch (g.gateType_) {
    case Gate::TIE0:
      r=0; break;
    case Gate::TIE1:
      r=1; break;
    case Gate::PO:
    case Gate::BUF:
      r = x[0];
      break;
    case Gate::INV:
      r = x[0] == 2 ? 2 : 1 - x[0];
      break;
    default: {
      bool isAnd = g.gateType_ >= Gate::AND2 && g.gateType_ <= Gate::NAND4;
      bool isOr = g.gateType_ >= Gate::OR2 && g.gateType_ <= Gate::NOR4;
      if (isAnd || isOr) {
        int ctrl = isAnd ? 0 : 1;
        r = 1 - ctrl;
        for (int z : x) {
          if (z == ctrl) {
            r = ctrl;
            break;
          }
          if (z == 2)
            r = 2;
        }
      } else {
        r = 0;
        for (int z : x) {
          if (z == 2) {
            r = 2;
            break;
          }
          r ^= z;
        }
      }
      if (g.isInverse() == H && r != 2)
        r = 1 - r;
    }
    }
    return fault == g.gateId_ && pin == -1 ? stuck : r;
  }
  std::vector<int> good(const std::string &p) const {
    std::vector<int> v(b.c.totalGate_, 2);
    for (int i = 0; i < b.c.numPI_; ++i)
      v[i] = p[i] == 'X' ? 2 : p[i] - '0';
    for (int i = b.c.numPI_; i < b.c.totalGate_; ++i)
      v[i] = eval(b.c.circuitGates_[i], v);
    return v;
  }
  bool detects(const std::string &p, int k) const {
    auto v = good(p), w = v;
    const auto &f = fl.extractedFaults_[k];
    if (f.faultyLine_ == 0 && f.gateID_ < b.c.numPI_)
      w[f.gateID_] = f.faultType_;
    for (int i = b.c.numPI_; i < b.c.totalGate_; ++i)
      w[i] = eval(b.c.circuitGates_[i], w, f.gateID_, f.faultyLine_ - 1,
                  f.faultType_);
    for (int i = b.c.numGate_ - b.c.numPO_; i < b.c.numGate_; ++i)
      if (v[i] != 2 && w[i] != 2 && v[i] != w[i])
        return true;
    return false;
  }
  void restore(const std::string &p) {
    auto v = good(p);
    for (int i = 0; i < b.c.totalGate_; ++i) {
      b.c.circuitGates_[i].atpgVal_ = v[i] == 2 ? X : Value(v[i]);
      b.c.circuitGates_[i].prevAtpgValStored_ = b.c.circuitGates_[i].atpgVal_;
    }
  }
  int solve(int k, bool secondary, std::string &out) {
    // A dead functional cone (e.g. a tie used only for inactive scan reset)
    // has no observation point. Do not send it into native backtrace.
    int target=fl.extractedFaults_[k].gateID_;
    if(b.c.circuitGates_[target].gateType_!=Gate::PO && b.c.circuitGates_[target].numFO_==0)
      return Atpg::FAULT_UNTESTABLE;
    // Catalog/graph preparation must not compute ATPG dominators or allocate
    // simulation state. Initialize once, immediately before the first target.
    if (!solver) {
      simulator.reset(new Simulator(&b.c));
      solver.reset(new Atpg(&b.c, simulator.get()));
      FanNativeAccess::setup(*solver);
    }
    restore(secondary ? cube : std::string(b.c.numPI_, 'X'));
    int r = FanNativeAccess::solve(*solver, fl.extractedFaults_[k], secondary,
                                   secondary ? 50 : limit);
    if (secondary)
      dtcBT += FanNativeAccess::backtracks(*solver);
    else
      primaryBT += FanNativeAccess::backtracks(*solver);
    out.clear();
    for (int i = 0; i < b.c.numPI_; ++i) {
      Value v = b.c.circuitGates_[i].atpgVal_;
      out += v == H || v == D ? '1' : v == L || v == B ? '0' : 'X';
    }
    return r;
  }
  std::vector<std::string> remaining() const {
    std::vector<std::string> r;
    for (size_t i = 0; i < ids.size(); ++i)
      if (!tried[i] && !detected[i])
        r.push_back(ids[i]);
    return r;
  }
  // FAN's no-test return is not itself a proof for repeated/reconvergent
  // inputs. Credit redundancy only after exhaustive independent simulation.
  // This never generates a fallback test: any counterexample leaves ABORT.
  bool provenRedundant(int k) {
    const auto &gate=b.c.circuitGates_[fl.extractedFaults_[k].gateID_];
    if(gate.gateType_!=Gate::PO && gate.numFO_==0) return true;
    if (b.c.numPI_ > 10)
      return false;
    for (unsigned bits = 0; bits < (1U << b.c.numPI_); ++bits) {
      std::string p(b.c.numPI_, '0');
      for (int j = 0; j < b.c.numPI_; ++j)
        p[j] = (bits & (1U << j)) ? '1' : '0';
      if (detects(p, k))
        return false;
    }
    return true;
  }
  Pattern patternFor(const std::string &p) {
    Pattern pattern(&b.c);
    for (int i = 0; i < b.c.numPI_; ++i)
      pattern.PI1_[i] = p[i] == 'X' ? X : Value(p[i] - '0');
    return pattern;
  }
  std::vector<bool> simulate(const std::string &p,
                             const std::vector<bool> &eligible) {
    auto faults = fl.extractedFaults_;
    FaultPtrList live;
    for (size_t k = 0; k < faults.size(); ++k)
      if (eligible[k]) {
        faults[k].faultState_ = Fault::UD;
        faults[k].detection_ = 0;
        live.push_back(&faults[k]);
      }
    simulator->parallelFaultFaultSimWithOnePattern(patternFor(p), live);
    std::vector<bool> result(faults.size());
    for (size_t k = 0; k < faults.size(); ++k)
      result[k] = eligible[k] && faults[k].faultState_ == Fault::DT;
    return result;
  }
  void finishPattern() {
    vector = cube;
    for (char &ch : vector)
      if (ch == 'X')
        ch = (rng() & 1) ? '1' : '0';
    if (!detects(vector, selected))
      throw std::runtime_error("FAN accepted cube lost primary detection");
    patterns.push_back(vector);
    std::vector<bool> eligible(ids.size());
    for (size_t k = 0; k < ids.size(); ++k)
      eligible[k] = !detected[k];
    auto found = simulate(vector, eligible);
    for (size_t k = 0; k < ids.size(); ++k)
      if (found[k]) {
        detected[k] = true;
        newly.push_back(ids[k]);
      }
    active = false;
  }
  py::dict complete() {
    auto d = summary(false);
    d["phase"] = "complete";
    d["selected_fault_id"] = ids[selected];
    d["target_status"] = status;
    d["generated_pattern"] = status == "detected";
    d["generated_test_vector"] = vector;
    d["dtc_attempted_fault_ids"] = attempted;
    d["dtc_embedded_fault_ids"] = embedded;
    d["newly_detected_fault_ids"] = newly;
    d["remaining_fault_ids"] = remaining();
    d["current_dtc_secondary_calls"] = dtcCalls;
    d["current_primary_backtracks"] = primaryBT;
    d["current_dtc_backtracks"] = dtcBT;
    d["current_podem_calls"] = primaryCalls;
    d["current_total_backtracks"] = primaryBT + dtcBT;
    return d;
  }
  py::dict nextBatch() {
    candidates.clear();
    const auto values = good(cube);
    // Restart the original-wire BFS for the current unknown PO after a cube
    // refinement. The fixed production budget permits exactly one signal
    // visit per PO, excluding the synthetic Circuit PO boundary gate.
    for (currentPO = std::max(currentPO, 0); currentPO < b.c.numPO_;
         ++currentPO) {
      const int boundary = b.c.numGate_ - b.c.numPO_ + currentPO;
      const int driver = b.c.circuitGates_[boundary].faninVector_[0];
      if (values[driver] != 2)
        continue;
      const int budget = 1;
      int visitedCount = 0;
      std::queue<int> pending;
      std::unordered_set<int> seen;
      pending.push(driver);
      while (!pending.empty() && visitedCount < budget) {
        const int wire = pending.front();
        pending.pop();
        if (!seen.insert(wire).second || values[wire] != 2)
          continue;
        ++visitedCount;
        // A wire's fault list consists of its GO plus every receiving GI
        // pin driven by that wire. Keep FAN catalog order deterministic.
        for (size_t k = 0; k < ids.size(); ++k) {
          const auto &fault = fl.extractedFaults_[k];
          const auto &gate = b.c.circuitGates_[fault.gateID_];
          const int activation = fault.faultyLine_
                                     ? gate.faninVector_[fault.faultyLine_ - 1]
                                     : fault.gateID_;
          if (activation != wire || tried[k] || detected[k] ||
              secondaryTried[k] || int(k) == selected || detects(cube, k))
            continue;
          candidates.push_back(k);
        }
        for (int fanin : b.c.circuitGates_[wire].faninVector_)
          if (values[fanin] == 2 && !seen.count(fanin))
            pending.push(fanin);
      }
      if (!candidates.empty()) {
        py::dict phase;
        phase["phase"] = "dtc";
        phase["selected_fault_id"] = ids[selected];
        std::vector<std::string> candidateIds;
        for (int k : candidates)
          candidateIds.push_back(ids[k]);
        phase["dtc_candidate_fault_ids"] = candidateIds;
        phase["dtc_batch_index"] = batch++;
        phase["unknown_po_id"] = b.outputs[currentPO];
        phase["select_fault_try"] = budget;
        phase["visited_wire_count"] = visitedCount;
        return phase;
      }
    }
    finishPattern();
    return complete();
  }
  py::dict summary(bool final) {
    py::dict d;
    int dc = 0, de = 0, re = 0, req = 0, ab = 0;
    for (size_t i = 0; i < ids.size(); ++i) {
      if (detected[i]) {
        ++dc;
        de += fl.extractedFaults_[i].equivalent_;
      }
      if (redundant[i] && !detected[i]) {
        ++re;
        req += fl.extractedFaults_[i].equivalent_;
      }
      if (aborted[i])
        ++ab;
    }
    d["pattern_count"] = final ? finalPatterns.size() : patterns.size();
    d["current_pattern_count"] = patterns.size();
    d["patterns_before_stc"] = patterns.size();
    d["patterns_after_stc"] = final ? finalPatterns.size() : patterns.size();
    d["detected_collapsed_faults"] = dc;
    d["detected_equivalent_faults"] = de;
    d["redundant_faults"] = re;
    d["redundant_equivalent_faults"] = req;
    d["aborted_faults"] = ab;
    d["uncollapsed_faults"] = fl.uncollapsedFaults_.size();
    d["podem_calls"] = primaryCalls;
    d["primary_podem_calls"] = primaryCalls;
    d["fan_calls"] = primaryCalls;
    d["dtc_secondary_calls"] = dtcCalls;
    d["primary_backtracks"] = primaryBT;
    d["dtc_backtracks"] = dtcBT;
    d["total_backtracks"] = primaryBT + dtcBT;
    d["stc_removed_patterns"] =
        final ? patterns.size() - finalPatterns.size() : 0;
    d["stc_shuffle_attempts"] = shuffleAttempts;
    d["stc_coverage_preserved"] = true;
    d["finalized"] = final;
    d["test_vectors"] = final ? finalPatterns : patterns;
    d["input_names"] = b.inputs;
    d["output_names"] = b.outputs;
    if(!b.scanChain.empty()) d["scan"]=b.graph()["scan"];
    return d;
  }

public:
  Session(std::string path, std::string library, int lim, int sd, bool dc, bool sc)
      : b(path, library), limit(lim), seed(sd), dtc(dc), stc(sc), rng(sd) {
    if (lim < 0)
      throw std::invalid_argument("backtrack limit must be nonnegative");
    fl.extractFaultFromCircuit(&b.c);
    // Original FAN appends automatically detected clock/scan port faults.
    // Functional policy catalogs exclude those from numerator and denominator.
    auto protocolFault=[](const Fault &f){return f.gateID_<0 || f.faultyLine_<0;};
    fl.extractedFaults_.erase(std::remove_if(fl.extractedFaults_.begin(),fl.extractedFaults_.end(),protocolFault),fl.extractedFaults_.end());
    fl.uncollapsedFaults_.erase(std::remove_if(fl.uncollapsedFaults_.begin(),fl.uncollapsedFaults_.end(),protocolFault),fl.uncollapsedFaults_.end());
    // Historical collapsing drops dangling INV/BUF input sites, including
    // buffers in Nangate tie cells used only by scan control pins. Use exact
    // physical data sites for scan/constant circuits; no synthetic weights.
    bool exact=!b.scanChain.empty();
    for(const auto &g:b.c.circuitGates_) exact=exact || g.gateType_==Gate::TIE0 || g.gateType_==Gate::TIE1;
    if(exact) fl.extractedFaults_=fl.uncollapsedFaults_;
    int n = fl.extractedFaults_.size();
    for (int k = 0; k < n; ++k) {
      auto &f = fl.extractedFaults_[k];
      std::string id =
          b.names[f.gateID_] +
          (f.faultyLine_ ? ":GI" + std::to_string(f.faultyLine_ - 1) : ":GO") +
          ":sa" + std::to_string(int(f.faultType_));
      lookup[id] = k;
      ids.push_back(id);
    }
    tried.resize(n);
    detected.resize(n);
    redundant.resize(n);
    aborted.resize(n);
  }
  py::dict catalog() {
    py::dict d;
    py::list fs;
    for (size_t k = 0; k < ids.size(); ++k) {
      auto &f = fl.extractedFaults_[k];
      auto &g = b.c.circuitGates_[f.gateID_];
      py::dict x;
      x["fault_id"] = ids[k];
      x["node_name"] = b.names[f.gateID_];
      x["gate_id"] = f.gateID_;
      x["gate_name"] = b.humanNames[f.gateID_];
      x["io"] = f.faultyLine_ ? 0 : 1;
      x["input_index"] = f.faultyLine_ - 1;
      std::string wire =
          f.faultyLine_ ? b.names[g.faninVector_[f.faultyLine_ - 1]] : "-";
      x["input_wire_name"] = wire;
      int occ = 0;
      for (int j = 0; j < f.faultyLine_ - 1; ++j)
        if (g.faninVector_[j] == g.faninVector_[f.faultyLine_ - 1])
          ++occ;
      x["input_occurrence"] = f.faultyLine_ ? occ : -1;
      x["fault_type"] = int(f.faultType_);
      x["eqv_fault_num"] = f.equivalent_;
      x["boundary_type"] = g.gateType_ == Gate::PO   ? "PO"
                           : g.gateType_ == Gate::PI ? "PI"
                                                     : "gate";
      fs.append(x);
    }
    d["faults"] = fs;
    d["uncollapsed_total"] = fl.uncollapsedFaults_.size();
    return d;
  }
  py::dict config() {
    py::dict d;
    d["backend"] = "FAN";
    d["protocol_version"] = "fan_verilog_fullscan_v3";
    d["primary_backtrack_limit"] = limit;
    d["primary_seed"] = seed;
    d["attempts_per_primary_fault"] = 1;
    d["dtc_enabled"] = dtc;
    d["dtc_secondary_backtrack_limit"] = 50;
    d["stc_enabled"] = stc;
    d["stc_reverse_order_enabled"] = true;
    d["stc_shuffle_seed"] = 7;
    d["stc_no_improvement_limit"] = 5;
    d["scoap_enabled"] = false;
    d["dtc_bfs_small_input_threshold"] = 32;
    d["dtc_bfs_small_select_fault_try"] = 1;
    d["dtc_bfs_default_select_fault_try"] = 1;
    d["dtc_rollback_algorithm"] = "accepted_pi_cube_resim_v1";
    return d;
  }
  std::vector<std::string> remaining_fault_ids() { return remaining(); }
  py::dict begin_step(const std::string &id) {
    if (active || finalized)
      throw std::invalid_argument("session has pending phase or is finalized");
    auto it = lookup.find(id);
    if (it == lookup.end() || tried[it->second] || detected[it->second])
      throw std::invalid_argument("fault is not remaining");
    selected = it->second;
    tried[selected] = true;
    ++primaryCalls;
    attempted.clear();
    embedded.clear();
    newly.clear();
    vector.clear();
    lastAttempt.clear();
    lastEmbed.clear();
    int r = solve(selected, false, cube);
    if (r == Atpg::PATTERN_FOUND && !detects(cube, selected))
      r = Atpg::ABORT;
    if (r != Atpg::PATTERN_FOUND) {
      status = r == Atpg::FAULT_UNTESTABLE && provenRedundant(selected)
                   ? "redundant"
                   : "aborted";
      redundant[selected] = status == "redundant";
      aborted[selected] = status == "aborted";
      return complete();
    }
    status = "detected";
    active = true;
    batch = 0;
    currentPO = -1;
    visited.assign(b.c.totalGate_, false);
    secondaryTried.assign(ids.size(), false);
    bfs = std::queue<int>();
    if (!dtc) {
      finishPattern();
      return complete();
    }
    return nextBatch();
  }
  py::dict rank_dtc_candidates(const std::vector<std::string> &order) {
    if (!active || candidates.empty())
      throw std::invalid_argument("no pending DTC batch");
    std::unordered_set<int> expected(candidates.begin(), candidates.end());
    if (order.size() != expected.size())
      throw std::invalid_argument("ranking must be candidate permutation");
    for (auto &id : order) {
      auto it = lookup.find(id);
      if (it == lookup.end() || !expected.erase(it->second))
        throw std::invalid_argument("ranking must be candidate permutation");
    }
    lastAttempt.clear();
    lastEmbed.clear();
    for (auto &id : order) {
      int k = lookup.at(id);
      secondaryTried[k] = true;
      attempted.push_back(id);
      lastAttempt.push_back(id);
      ++dtcCalls;
      std::string candidate;
      int r = solve(k, true, candidate);
      bool valid = r == Atpg::PATTERN_FOUND;
      for (int i = 0; i < b.c.numPI_; ++i)
        if (cube[i] != 'X' && candidate[i] != cube[i])
          valid = false;
      if (valid && detects(candidate, k) && detects(candidate, selected)) {
        cube = candidate;
        embedded.push_back(id);
        lastEmbed.push_back(id);
        restore(cube);
        auto currentValues = good(cube);
        int po = b.c.numGate_ - b.c.numPO_ + currentPO;
        if (currentValues[po] != 2)
          break;
      }
      restore(cube);
    }
    auto d = nextBatch();
    d["last_dtc_attempted_fault_ids"] = lastAttempt;
    d["last_dtc_embedded_fault_ids"] = lastEmbed;
    return d;
  }
  py::dict step(const std::string &id) {
    auto d = begin_step(id);
    while (py::cast<std::string>(d["phase"]) == "dtc") {
      auto order =
          py::cast<std::vector<std::string>>(d["dtc_candidate_fault_ids"]);
      d = rank_dtc_candidates(order);
    }
    return d;
  }
  py::dict result() {
    if (active || !remaining().empty())
      throw std::invalid_argument(
          "finish requires all primary faults processed");
    if (!finalized) {
      finalPatterns = patterns;
      if (stc) {
        auto compact = [&](std::vector<std::string> order) {
          std::vector<bool> covered(ids.size());
          std::vector<std::string> keep;
          for (auto &p : order) {
            bool adds = false;
            std::vector<bool> eligible(ids.size());
            for (size_t k = 0; k < ids.size(); ++k)
              eligible[k] = detected[k] && !covered[k];
            auto found = simulate(p, eligible);
            for (size_t k = 0; k < ids.size(); ++k)
              if (found[k]) {
                covered[k] = true;
                adds = true;
              }
            if (adds)
              keep.push_back(p);
          }
          for (size_t k = 0; k < ids.size(); ++k)
            if (detected[k] && !covered[k])
              throw std::runtime_error("STC lost coverage");
          return keep;
        };
        auto rev = finalPatterns;
        std::reverse(rev.begin(), rev.end());
        finalPatterns = compact(rev);
        std::mt19937 srng(7);
        int failures = 0;
        while (failures < 5) {
          auto shuffled = finalPatterns;
          std::shuffle(shuffled.begin(), shuffled.end(), srng);
          auto candidate = compact(shuffled);
          ++shuffleAttempts;
          if (candidate.size() < finalPatterns.size()) {
            finalPatterns = candidate;
            failures = 0;
          } else
            ++failures;
        }
      }
      finalized = true;
    }
    return summary(true);
  }
};
PYBIND11_MODULE(cpp_fan, m) {
  m.doc() = "Original FAN target ATPG with safe ranked dynamic compression";
  py::class_<Session>(m, "StuckAtSession")
      .def(py::init<std::string, std::string, int, int, bool, bool>(),
           py::arg("netlist_path"), py::arg("library_path"),
           py::arg("backtrack_limit") = 100, py::arg("seed") = 14,
           py::arg("dtc_enabled") = true, py::arg("stc_enabled") = true)
      .def("catalog", &Session::catalog)
      .def("config", &Session::config)
      .def("remaining_fault_ids", &Session::remaining_fault_ids)
      .def("begin_step", &Session::begin_step)
      .def("rank_dtc_candidates", &Session::rank_dtc_candidates)
      .def("step", &Session::step)
      .def("result", &Session::result);
  m.def("circuit_graph", [](std::string p, std::string l) {
    NativeCircuit c(p,l); return c.graph();
  }, py::arg("netlist_path"), py::arg("library_path"));
  m.def(
      "catalog_stuck_at",
      [](std::string p, std::string f) {
        Session s(p, f, 100, 14, true, true);
        return s.catalog();
      },
      py::arg("netlist_path"), py::arg("library_path"));
  m.def(
      "run_stuck_at_ordered",
      [](std::string p, std::string f, std::vector<std::string> order, int l,
         int seed, bool dtc, bool stc) {
        Session s(p, f, l, seed, dtc, stc);
        auto all = s.remaining_fault_ids();
        std::unordered_set<std::string> x(order.begin(), order.end());
        if (order.size() != all.size() || x.size() != all.size())
          throw std::invalid_argument(
              "order must contain all catalog faults exactly once");
        for (auto id : all)
          if (!x.count(id))
            throw std::invalid_argument("unknown fault in order");
        for (auto id : order) {
          auto rem = s.remaining_fault_ids();
          if (std::find(rem.begin(), rem.end(), id) != rem.end())
            s.step(id);
        }
        return s.result();
      },
      py::arg("netlist_path"), py::arg("library_path"),
      py::arg("ordered_fault_ids"), py::arg("backtrack_limit") = 100,
      py::arg("seed") = 14, py::arg("dtc_enabled") = true,
      py::arg("stc_enabled") = true);
}
